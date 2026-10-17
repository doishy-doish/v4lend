// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import {MockERC20} from "solmate/src/test/utils/mocks/MockERC20.sol";
import {WETH} from "solmate/src/tokens/WETH.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {IERC721} from "@openzeppelin/contracts/token/ERC721/IERC721.sol";
import {IERC4626} from "@openzeppelin/contracts/interfaces/IERC4626.sol";

import {IHooks} from "@uniswap/v4-core/src/interfaces/IHooks.sol";
import {Hooks} from "@uniswap/v4-core/src/libraries/Hooks.sol";
import {PoolKey} from "@uniswap/v4-core/src/types/PoolKey.sol";
import {PoolIdLibrary} from "@uniswap/v4-core/src/types/PoolId.sol";
import {Currency, CurrencyLibrary} from "@uniswap/v4-core/src/types/Currency.sol";
import {StateLibrary} from "@uniswap/v4-core/src/libraries/StateLibrary.sol";
import {TickMath} from "@uniswap/v4-core/src/libraries/TickMath.sol";
import {Constants} from "@uniswap/v4-core/test/utils/Constants.sol";
import {IPoolManager} from "@uniswap/v4-core/src/interfaces/IPoolManager.sol";

import {Actions} from "@uniswap/v4-periphery/src/libraries/Actions.sol";
import {IPositionManager} from "@uniswap/v4-periphery/src/interfaces/IPositionManager.sol";
import {NativeWrapper} from "@uniswap/v4-periphery/src/base/NativeWrapper.sol";
import {IWETH9} from "@uniswap/v4-periphery/src/interfaces/external/IWETH9.sol";

import {RevertHook} from "src/RevertHook.sol";
import {RevertHookState} from "src/hook/RevertHookState.sol";
import {PositionModeFlags} from "src/hook/lib/PositionModeFlags.sol";
import {HookFeeController} from "src/hook/HookFeeController.sol";
import {HookRouteController} from "src/hook/HookRouteController.sol";
import {LiquidityCalculator} from "src/shared/math/LiquidityCalculator.sol";
import {MockV4Oracle} from "test/utils/MockV4Oracle.sol";
import {MockERC4626Vault} from "test/utils/MockERC4626Vault.sol";
import {BaseTest} from "test/utils/BaseTest.sol";
import {V4PositionManagerDeployer} from "hookmate/artifacts/V4PositionManager.sol";
import {V4Vault} from "src/vault/V4Vault.sol";
import {InterestRateModel} from "src/vault/InterestRateModel.sol";

/// @notice Capped 4626 mock: maxRedeem bounded by an owner-set cap.
/// @dev Models cooldown / pause / withdrawal-queue / per-account-cap vaults.
contract CappedERC4626Vault is MockERC4626Vault {
    uint256 public redeemCap = type(uint256).max;

    constructor(IERC20 asset_, string memory name_, string memory symbol_)
        MockERC4626Vault(asset_, name_, symbol_)
    {}

    function setRedeemCap(uint256 cap) external {
        redeemCap = cap;
    }

    function maxRedeem(address owner) public view override returns (uint256) {
        uint256 base = super.maxRedeem(owner);
        return base < redeemCap ? base : redeemCap;
    }
}

/// @notice Echidna harness: hook custody conservation, vault debt-share
///         conservation, vault solvency. Param-driven, single deployer.
/// @dev Entry points never revert the sequence on purpose: forceExit may
///      revert (that IS the lock under test) and echidna skips past it.
contract CustodyInvariant is BaseTest {
    using PoolIdLibrary for PoolKey;
    using CurrencyLibrary for Currency;
    using StateLibrary for IPoolManager;

    Currency internal constant NATIVE = CurrencyLibrary.ADDRESS_ZERO;

    MockERC20 internal token1;
    IWETH9 internal weth;
    RevertHook internal hook;
    MockV4Oracle internal v4Oracle;
    CappedERC4626Vault internal wethVault;
    MockERC4626Vault internal token1Vault;
    V4Vault internal lendVault;

    PoolKey internal poolKey;
    uint256 internal tokenId;

    address[] internal vaults;
    uint256[] internal tokenIds;
    address[] internal owners;
    address[] internal tokens;

    receive() external payable {}

    function deployPositionManager() internal override {
        if (block.chainid == 31337) {
            WETH wrappedNative = new WETH();
            positionManager = IPositionManager(
                V4PositionManagerDeployer.deploy(
                    address(poolManager), address(permit2), 300_000, address(0), address(wrappedNative)
                )
            );
        } else {
            super.deployPositionManager();
        }
    }

    constructor() {
        deployArtifactsAndLabel();

        token1 = deployToken();
        weth = NativeWrapper(payable(address(positionManager))).WETH9();

        address flags = address(
            uint160(
                Hooks.AFTER_INITIALIZE_FLAG | Hooks.BEFORE_SWAP_FLAG | Hooks.AFTER_SWAP_FLAG
                    | Hooks.BEFORE_ADD_LIQUIDITY_FLAG | Hooks.AFTER_ADD_LIQUIDITY_FLAG
                    | Hooks.BEFORE_REMOVE_LIQUIDITY_FLAG | Hooks.AFTER_REMOVE_LIQUIDITY_FLAG
                    | Hooks.AFTER_ADD_LIQUIDITY_RETURNS_DELTA_FLAG | Hooks.AFTER_REMOVE_LIQUIDITY_RETURNS_DELTA_FLAG
            ) ^ (0x4445 << 144)
        );

        v4Oracle = new MockV4Oracle(positionManager);
        RevertHookStack memory stack = deployRevertHookStack(flags, v4Oracle, makeAddr("protocolFeeRecipient"));
        hook = stack.hook;

        wethVault = new CappedERC4626Vault(IERC20(address(weth)), "Capped Native Vault", "cWETH");
        token1Vault = new MockERC4626Vault(IERC20(address(token1)), "Token1 Vault", "vT1");

        hook.setAutoLendVault(address(0), IERC4626(address(wethVault)));
        hook.setAutoLendVault(address(token1), IERC4626(address(token1Vault)));

        poolKey = PoolKey({
            currency0: NATIVE,
            currency1: Currency.wrap(address(token1)),
            fee: 3000,
            tickSpacing: 60,
            hooks: IHooks(hook)
        });

        poolManager.initialize(poolKey, Constants.SQRT_PRICE_1_1);
        v4Oracle.setPoolKey(address(0), address(token1), poolKey);

        vm.deal(address(this), 1_000 ether);
        _mintPositionEth(poolKey, TickMath.minUsableTick(poolKey.tickSpacing), TickMath.maxUsableTick(poolKey.tickSpacing), 100e18);

        int24 currentTick = _getCurrentTick();
        int24 tickLower = _getTickLower(currentTick, poolKey.tickSpacing) - poolKey.tickSpacing;
        int24 tickUpper = _getTickLower(currentTick, poolKey.tickSpacing) + poolKey.tickSpacing;
        tokenId = _mintPositionEth(poolKey, tickLower, tickUpper, 100e18);
        tokenIds.push(tokenId);
        owners.push(address(this));

        hook.setPositionConfig(tokenId, _lendConfig());
        IERC721(address(positionManager)).setApprovalForAll(address(hook), true);

        vaults.push(address(wethVault));
        vaults.push(address(token1Vault));
        tokens.push(address(0));
        tokens.push(address(token1));

        InterestRateModel irm = new InterestRateModel(0, 0, 0, 0);
        lendVault = new V4Vault("WETH lending vault", "lWETH", address(weth), positionManager, irm, v4Oracle, weth);
        uint32 cf = uint32(uint256(2 ** 32) * 9 / 10);
        lendVault.setTokenConfig(address(0), cf, type(uint32).max);
        lendVault.setTokenConfig(address(token1), cf, type(uint32).max);
        lendVault.setHookAllowList(address(hook), true);
        lendVault.setTransformer(address(hook), true);
        lendVault.setLimits(0, 100e18, 100e18, 100e18, 100e18);
        hook.setVault(address(lendVault));
        weth.deposit{value: 20e18}();
        IERC20(address(weth)).approve(address(lendVault), 20e18);
        lendVault.deposit(20e18, address(this));
    }

    function _lendConfig() internal pure returns (RevertHookState.PositionConfig memory) {
        return RevertHookState.PositionConfig({
            modeFlags: PositionModeFlags.MODE_AUTO_LEND,
            autoCollectMode: RevertHookState.AutoCollectMode.NONE,
            autoExitIsRelative: false,
            autoExitTickLower: type(int24).min,
            autoExitTickUpper: type(int24).max,
            autoExitSwapOnLowerTrigger: true,
            autoExitSwapOnUpperTrigger: true,
            autoRangeLowerLimit: 0,
            autoRangeUpperLimit: 0,
            autoRangeLowerDelta: 0,
            autoRangeUpperDelta: 0,
            autoLendToleranceTick: 60,
            autoLeverageTargetBps: 0
        });
    }

    // ==================== fuzz entry points ====================

    function act_deposit(uint8 dir) external {
        _swapExactInputSingleEth(poolKey, dir % 2 == 0, 2e18, 0);
    }

    function act_forceExit(uint256 i) external {
        if (tokenIds.length == 0) return;
        hook.autoLendForceExit(tokenIds[i % tokenIds.length]);
    }

    function act_setCap(uint256 cap) external {
        (,,,, uint256 shares,,,) = hook.positionStates(tokenId);
        if (shares == 0) return;
        wethVault.setRedeemCap(cap % (shares + 1));
    }

    function act_withdraw(uint256 frac) external {
        (,,,, uint256 shares,,,) = hook.positionStates(tokenId);
        if (shares == 0) return;
        uint256 slice = (shares * (frac % 100)) / 100;
        if (slice == 0) return;
        hook.autoLendWithdraw(poolKey, tokenId, slice);
    }

    function act_newPosition(uint8 width) external {
        int24 spacing = poolKey.tickSpacing;
        int24 base = _getTickLower(_getCurrentTick(), spacing);
        int24 w = int24(uint24((width % 4 + 1) * uint24(spacing)));
        uint256 id = _mintPositionEth(poolKey, base - w, base + w, 10e18);
        hook.setPositionConfig(id, _lendConfig());
        tokenIds.push(id);
    }

    // ==================== invariants ====================

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
        (PoolKey memory k,) = lendVault.positionManager().getPoolAndPositionInfo(id);
        return Currency.unwrap(k.currency0) == t || Currency.unwrap(k.currency1) == t;
    }

    function echidna_debt_shares_conserved() public view returns (bool) {
        for (uint256 t = 0; t < tokens.length; t++) {
            uint192 recorded = lendVault.tokenConfigs(tokens[t]).totalDebtShares;
            uint256 summed;
            for (uint256 o = 0; o < owners.length; o++) {
                uint256 n = lendVault.loanCount(owners[o]);
                for (uint256 i = 0; i < n; i++) {
                    uint256 id = lendVault.loanAtIndex(owners[o], i);
                    if (poolContains(id, tokens[t])) {
                        summed += lendVault.loans(id).debtShares;
                    }
                }
            }
            if (summed != recorded) return false;
        }
        return true;
    }

    function echidna_solvent() public view returns (bool) {
        (uint256 debt, uint256 lent, uint256 balance,,,,) = lendVault.vaultInfo();
        return lent <= balance + debt;
    }

    // ==================== local helpers ====================

    function _mintPositionEth(PoolKey memory key, int24 tickLower, int24 tickUpper, uint128 liquidity)
        internal
        returns (uint256 newTokenId)
    {
        bytes memory actions =
            abi.encodePacked(uint8(Actions.MINT_POSITION), uint8(Actions.SETTLE_PAIR), uint8(Actions.SWEEP));
        bytes[] memory params = new bytes[](3);
        params[0] = abi.encode(
            key, tickLower, tickUpper, liquidity, type(uint256).max, type(uint256).max, address(this), bytes("")
        );
        params[1] = abi.encode(key.currency0, key.currency1, address(this));
        params[2] = abi.encode(address(0), address(this));

        positionManager.modifyLiquidities{value: 100 ether}(abi.encode(actions, params), block.timestamp);
        newTokenId = positionManager.nextTokenId() - 1;
    }

    function _swapExactInputSingleEth(PoolKey memory key, bool zeroForOne, uint128 amountIn, uint128 minAmountOut)
        internal
    {
        swapRouter.swapExactTokensForTokens{value: zeroForOne ? amountIn : 0}(
            amountIn, minAmountOut, zeroForOne, key, bytes(""), address(this), block.timestamp
        );
    }

    function _getCurrentTick() internal view returns (int24 tick) {
        (, tick,,) = StateLibrary.getSlot0(poolManager, poolKey.toId());
    }

    function _getTickLower(int24 tick, int24 tickSpacing) internal pure returns (int24) {
        return tick < 0 && tick % tickSpacing != 0 ? (tick / tickSpacing - 1) * tickSpacing : (tick / tickSpacing) * tickSpacing;
    }
}
