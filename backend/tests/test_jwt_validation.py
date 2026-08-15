from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
from cryptography.hazmat.primitives.asymmetric import ec

from app.core.security import decode_asymmetric_token, settings


def test_es256_validation_allows_small_issued_at_clock_skew():
    private_key = ec.generate_private_key(ec.SECP256R1())
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "sub": str(uuid4()),
            "aud": "authenticated",
            "iss": str(settings.SUPABASE_JWT_ISSUER).rstrip("/"),
            "iat": now + timedelta(seconds=5),
            "nbf": now + timedelta(seconds=5),
            "exp": now + timedelta(minutes=5),
        },
        private_key,
        algorithm="ES256",
    )

    claims = decode_asymmetric_token(token, private_key.public_key())

    assert claims["aud"] == "authenticated"
