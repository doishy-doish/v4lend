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

/// @notice MockERC4626Vault with an owner-settable redemption cap.
/// @dev Models a compliant ERC4626 whose maxRedeem drops below balance
///      (cooldown, pause, withdrawal queue, per-account cap).
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

/// @notice Demonstrates the hook autoLendForceExit custody lock (V4LE-96 variant).
/// @dev On the current code every assertion below PASSES: forceExit reverts,
///      disabling releases nothing, and the exit stays bricked. After the fix
///      (bounded redeem + residual-share transfer, mirroring AutoLend.forceExit),
///      assertions 4 and 6 must be updated to expect success.
contract HookAutoLendForceExitLockTest is BaseTest {
    using PoolIdLibrary for PoolKey;
    using CurrencyLibrary for Currency;
    using StateLibrary for IPoolManager;

    Currency internal constant NATIVE = CurrencyLibrary.ADDRESS_ZERO;

    MockERC20 internal token1;
    IWETH9 internal weth;
    RevertHook internal hook;
    HookFeeController internal feeController;
    HookRouteController internal routeController;
    LiquidityCalculator internal liquidityCalculator;
    MockV4Oracle internal v4Oracle;
    CappedERC4626Vault internal wethVault;
    MockERC4626Vault internal token1Vault;

    PoolKey internal poolKey;
    uint256 internal tokenId;
    int24 internal positionTickLower;
    int24 internal positionTickUpper;

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

    function setUp() public {
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
        feeController = stack.feeController;
        routeController = stack.routeController;
        liquidityCalculator = stack.liquidityCalculator;

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
        positionTickLower = _getTickLower(currentTick, poolKey.tickSpacing) - poolKey.tickSpacing;
        positionTickUpper = _getTickLower(currentTick, poolKey.tickSpacing) + poolKey.tickSpacing;
        tokenId = _mintPositionEth(poolKey, positionTickLower, positionTickUpper, 100e18);

        hook.setPositionConfig(
            tokenId,
            RevertHookState.PositionConfig({
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
            })
        );
        IERC721(address(positionManager)).setApprovalForAll(address(hook), true);
    }

    function _emptyConfig() internal pure returns (RevertHookState.PositionConfig memory cfg) {
        cfg = RevertHookState.PositionConfig({
            modeFlags: PositionModeFlags.MODE_NONE,
            autoCollectMode: RevertHookState.AutoCollectMode.NONE,
            autoExitIsRelative: false,
            autoExitTickLower: type(int24).min,
            autoExitTickUpper: type(int24).max,
            autoExitSwapOnLowerTrigger: true,
            autoExitSwapOnUpperTrigger: true,
            autoRangeLowerLimit: type(int24).min,
            autoRangeUpperLimit: type(int24).max,
            autoRangeLowerDelta: 0,
            autoRangeUpperDelta: 0,
            autoLendToleranceTick: 0,
            autoLeverageTargetBps: 0
        });
    }

    function test_autoLendForceExit_locksWhenMaxRedeemBelowShares() public {
        // 1. Deposit lands through the hook's own trigger path (price out of range).
        _swapExactInputSingleEth(poolKey, true, 2e18, 0);

        (,,,, uint256 shares,,,) = hook.positionStates(tokenId);
        assertGt(shares, 0, "deposit should mint vault shares");
        assertEq(wethVault.balanceOf(address(hook)), shares, "hook should hold the shares");

        // 2. Cap maxRedeem below the recorded shares.
        wethVault.setRedeemCap(shares - 1);
        assertLt(wethVault.maxRedeem(address(hook)), shares, "cap should bind");

        // 3. The only exit reverts: bare redeem(shares) exceeds maxRedeem.
        vm.expectRevert(bytes("ERC4626: redeem more than max"));
        hook.autoLendForceExit(tokenId);

        // 4. Disabling automation succeeds but releases nothing.
        hook.setPositionConfig(tokenId, _emptyConfig());

        (,,,, uint256 sharesAfter,,,) = hook.positionStates(tokenId);
        assertEq(sharesAfter, shares, "disable must not release shares");
        assertEq(wethVault.balanceOf(address(hook)), shares, "hook still holds shares");

        // 5. The exit stays bricked: no state accumulates toward recovery.
        vm.expectRevert(bytes("ERC4626: redeem more than max"));
        hook.autoLendForceExit(tokenId);
    }
}
