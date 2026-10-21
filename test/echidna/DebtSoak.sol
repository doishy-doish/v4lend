// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import {IERC721} from "@openzeppelin/contracts/token/ERC721/IERC721.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {IERC4626} from "@openzeppelin/contracts/interfaces/IERC4626.sol";
import {SoakBase} from "./SoakBase.sol";

/// @notice Debt campaign: borrow/repay paths with conservation checks.
contract DebtSoak is SoakBase {
    function act_borrow(uint256 i, uint128 amt) external {
        if (tokenIds.length == 0) return;
        uint256 id = tokenIds[i % tokenIds.length];
        IERC721(address(positionManager)).setApprovalForAll(address(lendVault), true);
        try lendVault.create(id, address(this)) {} catch {}
        uint256 bounded = uint256(amt) % 5e18;
        if (bounded == 0) return;
        try lendVault.borrow(id, bounded) {} catch {}
    }

    function act_repay(uint256 i, uint128 amt) external {
        if (tokenIds.length == 0) return;
        uint256 id = tokenIds[i % tokenIds.length];
        uint256 bounded = uint256(amt) % 5e18;
        if (bounded == 0) return;
        IERC20(address(weth)).approve(address(lendVault), bounded);
        try lendVault.repay(id, bounded, false) {} catch {}
    }

    function echidna_debt_shares_conserved() public view returns (bool) {
        for (uint256 t = 0; t < tokens.length; t++) {
            (,, uint192 recorded) = lendVault.tokenConfigs(tokens[t]);
            uint256 summed;
            for (uint256 o = 0; o < owners.length; o++) {
                uint256 n = lendVault.loanCount(owners[o]);
                for (uint256 li = 0; li < n; li++) {
                    uint256 id = lendVault.loanAtIndex(owners[o], li);
                    if (poolContains(id, tokens[t])) {
                        (uint256 ds) = lendVault.loans(id);
                        summed += ds;
                    }
                }
            }
            if (summed != recorded) return false;
        }
        return true;
    }

    function echidna_solvent() public view returns (bool) {
        (uint256 debt, uint256 lent, uint256 balance,,,) = lendVault.vaultInfo();
        return lent <= balance + debt;
    }
}
