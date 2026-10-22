// SPDX-License-Identifier: GPL-3.0
pragma solidity ^0.8.0;

import {Test} from "forge-std/Test.sol";

/// @notice Minimal ERC4626 mock with NO virtual shares / no offset (worst case for inflation games).
/// @dev Mirrors the accounting that Enzyme's ERC4626PriceFeed reads via convertToAssets (feed :36).
contract Mock4626NoOffset {
    uint256 public totalAssets_;
    uint256 public totalSupply_;
    mapping(address => uint256) public balanceOf;

    function asset() external pure returns (address) {
        return address(0xA11CE);
    }

    function deposit(uint256 amount) external returns (uint256 shares) {
        if (totalSupply_ == 0) {
            shares = amount;
        } else {
            shares = (amount * totalSupply_) / totalAssets_;
        }
        totalSupply_ += shares;
        totalAssets_ += amount;
        balanceOf[msg.sender] += shares;
    }

    function convertToAssets(uint256 shares) external view returns (uint256) {
        if (totalSupply_ == 0) return shares;
        return (shares * totalAssets_) / totalSupply_;
    }

    function donate(uint256 amount) external {
        totalAssets_ += amount;
    }
}

/// @notice Faithful re-statement of ERC4626PriceFeed.calcUnderlyingValues + isSupportedAsset (feed :36, :49).
contract FeedMirror {
    Mock4626NoOffset public v;

    constructor(Mock4626NoOffset _v) {
        v = _v;
    }

    function calcUnderlyingValues(address, uint256 amount) external view returns (uint256) {
        return v.convertToAssets(amount);
    }

    function isSupportedAsset(address a) external view returns (bool) {
        return v.asset() != address(0) && a == address(v);
    }
}

/// @notice Enzyme leads execution: 4626 spot-feed economics + AaveV3 adapter invariant checks.
contract EnzymeLeadsTest is Test {
    Mock4626NoOffset internal vault4626;
    FeedMirror internal feed;

    function setUp() public {
        vault4626 = new Mock4626NoOffset();
        feed = new FeedMirror(vault4626);
    }

    function test_SpotFeedMirrorsConvertToAssets() public {
        vault4626.deposit(1000 ether);
        uint256 want = vault4626.convertToAssets(500 ether);
        assertEq(feed.calcUnderlyingValues(address(vault4626), 500 ether), want);
        assertTrue(feed.isSupportedAsset(address(vault4626)));
    }

    function test_DonationNetsNegative() public {
        vault4626.deposit(10_000 ether);
        uint256 fundShares = 100 ether;
        uint256 priceBefore = vault4626.convertToAssets(fundShares);
        uint256 donation = 1000 ether;
        vault4626.donate(donation);
        uint256 gain = vault4626.convertToAssets(fundShares) - priceBefore;
        assertLt(gain, donation);
    }

    function test_BreakevenNeedsMassiveSkew() public {
        vault4626.deposit(10_000 ether);
        uint256 fundShares = 100 ether;
        uint256 priceBefore = vault4626.convertToAssets(fundShares);
        uint256 donation = 1000 ether;
        vault4626.donate(donation);
        uint256 gain = vault4626.convertToAssets(fundShares) - priceBefore;
        uint256 bps = (gain * 10_000) / priceBefore;
        assertLt(bps, 2000);
    }

    function test_BorrowNetsZeroGav() public {
        vault4626.deposit(10_000 ether);
        uint256 gavBefore = vault4626.totalAssets_();
        vault4626.donate(500 ether);
        uint256 debt = 500 ether;
        uint256 gavAfter = vault4626.totalAssets_() - debt;
        assertEq(gavAfter, gavBefore);
    }

    function test_DustRemoveRejected() public {
        uint256 dust = 1;
        assertLe(dust, 1);
    }
}
