"""
Cryptographic utilities for Solana keypairs, Base58 encoding, and Program Derived Addresses (PDA).
Pure Python implementation compliant with Solana standards and RFC 8032.
"""

import hashlib
import secrets

B58_CHARS = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

def b58encode(b: bytes) -> str:
    n = int.from_bytes(b, "big")
    res = []
    while n > 0:
        n, r = divmod(n, 58)
        res.append(B58_CHARS[r])
    pad = 0
    for byte in b:
        if byte == 0: pad += 1
        else: break
    return "1" * pad + "".join(reversed(res))

def b58decode(s: str) -> bytes:
    n = 0
    for char in s:
        n = n * 58 + B58_CHARS.index(char)
    res = n.to_bytes((n.bit_length() + 7) // 8, "big") if n > 0 else b""
    pad = 0
    for char in s:
        if char == "1": pad += 1
        else: break
    return b"\x00" * pad + res

# Ed25519 Curve Arithmetic for Key Generation
q = 2**255 - 19
d = -121665 * pow(121666, q - 2, q) % q
I = pow(2, (q - 1) // 4, q)

def inv(z):
    return pow(z, q - 2, q)

def xrecover(y):
    xx = (y * y - 1) * inv(d * y * y + 1)
    x = pow(xx, (q + 3) // 8, q)
    if (x * x - xx) % q != 0: x = (x * I) % q
    if x % 2 != 0: x = q - x
    return x

By = 4 * inv(5) % q
Bx = xrecover(By)
B = (Bx, By)

def edwards_add(P, Q):
    x1, y1 = P
    x2, y2 = Q
    x3 = (x1*y2 + x2*y1) * inv(1 + d*x1*x2*y1*y2) % q
    y3 = (y1*y2 + x1*x2) * inv(1 - d*x1*x2*y1*y2) % q
    return (x3, y3)

def scalarmult(P, e):
    if e == 0: return (0, 1)
    Q = scalarmult(P, e // 2)
    Q = edwards_add(Q, Q)
    if e & 1: Q = edwards_add(Q, P)
    return Q

def generate_keypair():
    """Generates a fresh Solana Ed25519 keypair."""
    sk_bytes = secrets.token_bytes(32)
    h = hashlib.sha512(sk_bytes).digest()
    a = 2**254 + sum(2**i * ((h[i // 8] >> (i % 8)) & 1) for i in range(3, 254))
    A = scalarmult(B, a)
    x, y = A
    s = bytearray(y.to_bytes(32, "little"))
    if x & 1: s[31] |= 0x80
    pk_bytes = bytes(s)
    
    pubkey_b58 = b58encode(pk_bytes)
    privkey_b58 = b58encode(sk_bytes + pk_bytes)
    return {
        "publicKey": pubkey_b58,
        "privateKey": privkey_b58,
        "publicKeyBytes": pk_bytes,
        "secretKeyBytes": sk_bytes
    }

def find_program_address(seeds: list[bytes], program_id_bytes: bytes) -> tuple[str, int]:
    """Derives a Program Derived Address (PDA) on Solana."""
    bump = 255
    while bump >= 0:
        hasher = hashlib.sha256()
        for seed in seeds:
            hasher.update(seed)
        hasher.update(bytes([bump]))
        hasher.update(program_id_bytes)
        hasher.update(b"ProgramDerivedAddress")
        pda_bytes = hasher.digest()
        
        # Check if the derived point is off-curve
        y = int.from_bytes(pda_bytes[:32], "little") % q
        xx = (y * y - 1) * inv(d * y * y + 1)
        if pow(xx, (q - 1) // 2, q) != 1: # Not a quadratic residue = off curve!
            return b58encode(pda_bytes), bump
        bump -= 1
    return b58encode(pda_bytes), 0
