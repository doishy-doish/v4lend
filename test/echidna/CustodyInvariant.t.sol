// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import {IERC4626} from "@openzeppelin/contracts/interfaces/IERC4626.sol";
import {SoakBase} from "./SoakBase.sol";

/// @notice Echidna harness: hook custody conservation, vault debt-share
///         conservation, vault solvency. Param-driven, single deployer.
contract CustodyInvariant is SoakBase {
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

    function poolContains(uint256 id, address t) internal view returns (bool) {
        return SoakBase.poolContains(id, t);
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
