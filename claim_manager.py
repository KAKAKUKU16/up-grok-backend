"""
Creator Fee Claim Manager
Verifies creator claim codes, manages 3 SOL bonuses, and tracks perpetual fee shares.
"""

import time
from pump_deployer import _load_launches, _save_launches
from crypto_utils import b58decode

def verify_and_claim(claim_code: str, wallet_address: str) -> dict:
    """
    Verifies a creator claim code and registers the 3 SOL bonus payout to the provided wallet.
    """
    claim_code = claim_code.strip().upper()
    wallet_address = wallet_address.strip()

    # Validate Solana address format
    try:
        decoded = b58decode(wallet_address)
        if len(decoded) != 32:
            return {"success": False, "error": "Invalid Solana wallet address length (must be 32 bytes)."}
    except Exception:
        return {"success": False, "error": "Invalid Base58 Solana wallet address."}

    launches = _load_launches()
    match = None
    for token in launches:
        if token.get("claimCode") == claim_code:
            match = token
            break

    if not match:
        return {
            "success": False,
            "error": "Claim code not found. Please double-check your code (e.g. UP-XXXX-XXXX)."
        }

    if match.get("claimed"):
        return {
            "success": False,
            "error": f"This code has already been claimed by wallet: {match.get('claimedWallet')[:6]}...{match.get('claimedWallet')[-4:]}"
        }

    # Mark as successfully claimed
    match["claimed"] = True
    match["claimedWallet"] = wallet_address
    match["claimedAt"] = int(time.time())
    match["bonusAmount"] = "3.0 SOL"
    match["feeSharePct"] = "20%"
    _save_launches(launches)

    return {
        "success": True,
        "message": f"Successfully verified! 3 SOL bonus claimed for ${match.get('symbol')}!",
        "tokenName": match.get("name"),
        "symbol": match.get("symbol"),
        "mint": match.get("mint"),
        "wallet": wallet_address,
        "bonusSOL": 3.0,
        "perpetualRevShare": "20%",
        "status": "Claim Approved · Payout Queued"
    }
