// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SoakBase} from "./SoakBase.sol";

/// @notice Solvency campaign: violent price moves plus lending flows.
contract SolvencySoak is SoakBase {
    function act_bigSwap(uint8 dir) external {
        _swapExactInputSingleEth(poolKey, dir % 2 == 0, 20e18, 0);
    }

    function act_lendDeposit() external {
        weth.deposit{value: 1e18}();
        IERC20(address(weth)).approve(address(lendVault), 1e18);
        try lendVault.deposit(1e18, address(this)) {} catch {}
    }

    function echidna_solvent() public view returns (bool) {
        (uint256 debt, uint256 lent, uint256 balance,,,) = lendVault.vaultInfo();
        return lent <= balance + debt;
    }

    function echidna_custody_conserved() public view returns (bool) {
        for (uint256 v = 0; v < vaults.length; v++) {
            uint256 recorded;
            for (uint256 i = 0; i < tokenIds.length; i++) {
                (,,,, uint256 shares,, address positionVault,) = hook.positionStates(tokenIds[i]);
                if (positionVault == vaults[v]) recorded += shares;
            }
            if (IERC4626(vaults[v]).balanceOf(address(hook)) < recorded) return false;
        }
        return true;
    }
}
