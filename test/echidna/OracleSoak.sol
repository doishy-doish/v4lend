// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import {SoakBase} from "./SoakBase.sol";

/// @notice Oracle-window campaign: mint and configure at manipulated prices.
/// Conservation must survive displacement inside the oracle window.
contract OracleSoak is SoakBase {
    function act_movePrice(uint8 dir, uint8 size) external {
        uint128 amt = uint128((uint256(size) % 5 + 1) * 4e18);
        _swapExactInputSingleEth(poolKey, dir % 2 == 0, amt, 0);
    }

    function act_mintAtPrice(uint8 width) external {
        int24 spacing = poolKey.tickSpacing;
        int24 base = _getTickLower(_getCurrentTick(), spacing);
        int24 w = int24(uint24((width % 4 + 1) * uint24(spacing)));
        uint256 id = _mintPositionEth(poolKey, base - w, base + w, 10e18);
        hook.setPositionConfig(id, _lendConfig());
        tokenIds.push(id);
    }

    function echidna_solvent() public view returns (bool) {
        (uint256 debt, uint256 lent, uint256 balance,,,) = lendVault.vaultInfo();
        return lent <= balance + debt;
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
}
