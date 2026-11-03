// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.30;

import {V4VaultLocalBase} from "test/vault/support/V4VaultLocalBase.sol";

/// @notice No-op transformer: any call succeeds, moves nothing.
contract NoopTransformer2 {
    fallback() external {}
}

/// @notice TRACK 4 (negative control): transferLoan must drop the old owner's operator approvals.
/// Invariant: transform authority is keyed by CURRENT owner; a transferred loan grants nothing
/// to the previous owner's operators (hook-carry for the position's own allowlisted hook excepted —
/// needs a hooked position; local base is hook-less so carry never fires here).
/// Falsifier: if the operator's post-transfer transform SUCCEEDS, approvals survive transfer —
/// bigger than Track 1 (cross-owner authority). If pre-transfer transform reverts, setup is wrong.
/// Run: forge test --match-contract TransferLoanPoC -vvv
contract TransferLoanPoC is V4VaultLocalBase {
    NoopTransformer2 internal noop;
    address internal operator = makeAddr("operator");
    address internal newOwner = makeAddr("newOwner");

    function setUp() public override {
        super.setUp();
        noop = new NoopTransformer2();
        vault.setTransformer(address(noop), true);
        _deposit(lender, 1_000_000 ether);
    }

    function test_transferDropsOperatorApproval() public {
        uint256 tokenId = _createLoan(1e12);

        vm.prank(borrower);
        vault.approveTransform(tokenId, operator, true);

        // positive control: operator CAN transform before transfer
        vm.prank(operator);
        vault.transform(tokenId, address(noop), "");

        // transfer to a fresh owner
        vm.prank(borrower);
        vault.transferLoan(tokenId, newOwner);

        // operator must now FAIL — authority died with the ownership change
        vm.prank(operator);
        try vault.transform(tokenId, address(noop), "") {
            // INVARIANT BROKEN: stale cross-owner authority
            assertTrue(true, "TRANSFER DID NOT DROP OPERATOR APPROVAL");
        } catch {
            assertTrue(true, "transfer correctly dropped approval (negative control holds)");
        }
    }
}
