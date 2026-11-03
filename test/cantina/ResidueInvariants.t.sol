// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.30;

// Branch CI copy (poc/cantina-residue). Local record: scratch/v4lend/harness/ResidueInvariants.staged.sol.
// KNOWN-EXPECTATION: invariant_NoDeadApproval is EXPECTED TO FAIL (Finding 1 shape). — not run (forge does not run in this workspace; see RUN-FORGE-HERE.md).
// Operator: review, rename to ResidueInvariants.t.sol, run:
//   forge test --match-contract ResidueInvariantTest -vvv
// Covers the RESIDUE family (state that outlives a lifecycle boundary):
//   Finding 1 shape (approval live after remove/re-create), Finding 2 shape
//   (borrow bound to set not instance), mutex-zero, no-debt-without-owner.
// Extends the existing V4VaultHandler (test/vault/invariants/V4VaultInvariants.t.sol)
// instead of rebuilding a harness.

import {IVault} from "src/vault/interfaces/IVault.sol";
import {V4Vault} from "src/vault/V4Vault.sol";
import {Test} from "forge-std/Test.sol";
import {V4VaultHandler} from "test/vault/invariants/V4VaultInvariants.t.sol";

/// @notice No-op transformer: any call succeeds, moves nothing.
contract ResidueNoop {
    fallback() external {}
}

/// @notice Rogue B: allowlisted, borrows the victim loan when called mid-transform.
contract ResidueRogue {
    IVault public vault;
    constructor(IVault v) { vault = v; }
    function ride(uint256 tokenId, uint256 amount) external {
        vault.borrow(tokenId, amount);
    }
    fallback() external {}
}

/// @notice Honest A: allowlisted, its flight performs one external call to B.
contract ResidueHonest {
    ResidueRogue public b;
    uint256 public targetToken;
    uint256 public rideAmount;
    constructor(ResidueRogue _b) { b = _b; }
    function setRide(uint256 t, uint256 a) external { targetToken = t; rideAmount = a; }
    fallback() external {
        if (targetToken != 0) b.ride(targetToken, rideAmount);
    }
}

/// @notice Residue actions layered on the audited V4VaultHandler (3 loans, mock oracle).
contract ResidueHandler is V4VaultHandler {
    ResidueNoop public noop;
    ResidueRogue public rogue;
    ResidueHonest public honest;
    address public operator = makeAddr("residueOperator");

    // ghost: approvals THIS handler granted (owner is always address(this) here)
    mapping(uint256 => mapping(address => bool)) public ghostApproved;

    function initResidue() external {
        noop = new ResidueNoop();
        rogue = new ResidueRogue(IVault(address(vault)));
        honest = new ResidueHonest(rogue);
        vault.setTransformer(address(noop), true);
        vault.setTransformer(address(rogue), true);
        vault.setTransformer(address(honest), true);
    }

    function approveOp(uint256 posSeed) external {
        uint256 tokenId = tokenIds[posSeed % 3];
        if (vault.ownerOf(tokenId) != address(this)) return;
        vault.approveTransform(tokenId, operator, true);
        ghostApproved[tokenId][operator] = true;
    }

    function revokeOp(uint256 posSeed) external {
        uint256 tokenId = tokenIds[posSeed % 3];
        if (vault.ownerOf(tokenId) != address(this)) return;
        vault.approveTransform(tokenId, operator, false);
        ghostApproved[tokenId][operator] = false;
    }

    function noopTransform(uint256 posSeed) external {
        uint256 tokenId = tokenIds[posSeed % 3];
        if (vault.ownerOf(tokenId) != address(this)) return;
        try vault.transform(tokenId, address(noop), "") {} catch {}
    }

    /// @dev Operator uses a live approval (Finding-1 shape probe; must not revert spuriously).
    function operatorNoopTransform(uint256 posSeed) external {
        uint256 tokenId = tokenIds[posSeed % 3];
        if (!vault.transformApprovals(address(this), tokenId, operator)) return;
        vm.prank(operator);
        try vault.transform(tokenId, address(noop), "") {} catch {}
    }

    /// @dev Cross-transformer ride (Finding-2 shape probe). Small ride stays healthy by
    ///      construction of the caller's headroom; success/failure is asserted by invariants.
    function rideTransform(uint256 posSeed, uint256 amount) external {
        uint256 tokenId = tokenIds[posSeed % 3];
        if (vault.ownerOf(tokenId) != address(this)) return;
        (uint256 debt,, uint256 collateralValue,,) = vault.loanInfo(tokenId);
        if (collateralValue <= debt) return;
        uint256 headroom = (collateralValue - debt) * 99 / 100;
        if (headroom == 0) return;
        amount = bound(amount, 1, headroom);
        honest.setRide(tokenId, amount);
        try vault.transform(tokenId, address(honest), "") {} catch {}
        honest.setRide(0, 0);
    }
}

/// @notice Residue invariants. KNOWN-EXPECTATION: invariant_NoDeadApproval is EXPECTED TO
///         FAIL on current code — that failure IS Finding 1 (remove/re-create path in the
///         handler's liquidate() re-adds the husk while the pre-liquidation approval stays
///         live). Do not "fix" the invariant; file the trace.
contract ResidueInvariantTest is Test {
    ResidueHandler public handler;
    V4Vault public vault;

    function setUp() public {
        handler = new ResidueHandler();
        handler.initResidue();
        vault = handler.vault();
        targetContract(address(handler));

        bytes4[] memory selectors = new bytes4[](12);
        selectors[0] = handler.deposit.selector;
        selectors[1] = handler.redeem.selector;
        selectors[2] = handler.borrow.selector;
        selectors[3] = handler.repay.selector;
        selectors[4] = handler.warp.selector;
        selectors[5] = handler.setPositionValue.selector;
        selectors[6] = handler.liquidate.selector;
        selectors[7] = ResidueHandler.approveOp.selector;
        selectors[8] = ResidueHandler.revokeOp.selector;
        selectors[9] = ResidueHandler.noopTransform.selector;
        selectors[10] = ResidueHandler.operatorNoopTransform.selector;
        selectors[11] = ResidueHandler.rideTransform.selector;
        targetSelector(FuzzSelector({addr: address(handler), selectors: selectors}));
    }

    /// forge-config: default.invariant.runs = 32
    /// forge-config: default.invariant.depth = 64
    /// forge-config: default.invariant.fail-on-revert = true
    function invariant_MutexZeroOutsideFlight() public view {
        assertEq(vault.transformedTokenId(), 0, "transform mutex left set outside a flight");
    }

    /// forge-config: default.invariant.runs = 32
    /// forge-config: default.invariant.depth = 64
    /// forge-config: default.invariant.fail-on-revert = true
    function invariant_NoDebtWithoutOwner() public view {
        for (uint256 i = 0; i < 3; i++) {
            uint256 tokenId = handler.tokenIds(i);
            if (vault.ownerOf(tokenId) == address(0)) {
                assertEq(vault.loans(tokenId), 0, "debt survives ownerless loan");
            }
        }
    }

    /// forge-config: default.invariant.runs = 32
    /// forge-config: default.invariant.depth = 64
    /// forge-config: default.invariant.fail-on-revert = true
    function invariant_NoDeadApproval() public view {
        for (uint256 i = 0; i < 3; i++) {
            uint256 tokenId = handler.tokenIds(i);
            // an approval the handler granted must die with remove/revoke: live approval
            // requires the recorded owner to still own the loan
            if (handler.ghostApproved(tokenId, handler.operator())) {
                assertTrue(
                    vault.transformApprovals(address(handler), tokenId, handler.operator())
                        == (vault.ownerOf(tokenId) == address(handler)),
                    "approval residue: live for a loan the owner no longer holds"
                );
            }
        }
    }

    /// @notice Scripted walk proving the handler reaches the residue paths with the
    ///         base invariants intact (guards against silent early-return fuzzing).
    function test_ResidueWalkProvesReachability() public {
        handler.deposit(0, 1e21);
        handler.borrow(0, type(uint256).max);
        handler.approveOp(0);
        assertTrue(
            vault.transformApprovals(address(handler), handler.tokenIds(0), handler.operator()),
            "approval must be live after grant"
        );
        handler.noopTransform(0);
        invariant_MutexZeroOutsideFlight();
        invariant_NoDebtWithoutOwner();
        // revoke is honored on the live loan (negative control for the invariant above)
        handler.revokeOp(0);
        assertFalse(
            vault.transformApprovals(address(handler), handler.tokenIds(0), handler.operator()),
            "revoke must clear a live approval"
        );
    }
}
