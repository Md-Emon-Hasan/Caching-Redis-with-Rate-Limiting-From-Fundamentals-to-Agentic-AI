"""
============================================================================
 PHASE 5 - CONCEPT 4: FEATURE STORE CACHE (Online Features for ML)
============================================================================

WHAT IS A "FEATURE"?
--------------------
In machine learning, a "feature" is an input signal your model uses to make
a prediction. For a fraud-detection model, features might be:
    - user's average transaction amount (last 30 days)
    - number of transactions in the last hour
    - account age in days
    - is the country different from usual?

WHAT IS A FEATURE STORE?
------------------------
A feature store is the system that serves these features to models. It has
two "sides":

  OFFLINE side : big historical tables (in a warehouse) used for TRAINING.
  ONLINE  side : a super-fast key-value store used at PREDICTION time, where
                 you need the features in single-digit milliseconds.

    Model needs to predict NOW
              |
              v
      "give me features for user_123"   <-- must be VERY fast
              |
              v
        [Online Feature Store]  <-- THIS is where Redis shines

WHY REDIS?
----------
When a request comes in ("is THIS transaction fraud?"), your model has a
few milliseconds to respond. You cannot run a heavy SQL aggregation over
millions of rows in that window. Instead, you pre-compute the features and
store them in Redis, keyed by entity id (user_id, product_id, ...).

    write side (batch/streaming job)  ->  Redis  ->  read side (model serving)

This is slightly different from the caches above:
  - LLM/embedding/retrieval caches are "compute on miss".
  - A feature store is usually "pre-computed and pushed"; the model side
    only ever READS. Redis here is the low-latency serving layer.

We use a Redis HASH per entity so related features live together and can be
read in one call.
============================================================================
"""

import time
import json

import redis


r = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)


# ---------------------------------------------------------------------------
# 1. WRITE SIDE  -  a batch/streaming job computes & pushes features
# ---------------------------------------------------------------------------
# In production this runs on a schedule (e.g. every 5 min) or reacts to a
# stream (Kafka). It does the heavy computation ONCE, so serving is instant.
def write_features(entity_type: str, entity_id: str,
                   features: dict, ttl_seconds: int | None = None) -> None:
    """
    Store a group of features for one entity.

    We use a Redis HASH:  key = "features:user:123",  fields = feature names.
    HSET writes all fields in one call. Related data updated together lives
    together (remember this pattern from good key design).
    """
    key = f"features:{entity_type}:{entity_id}"

    # Redis hash values must be strings, so JSON-encode each value. This lets
    # us store numbers, bools, and even lists uniformly.
    mapping = {name: json.dumps(value) for name, value in features.items()}

    # HSET writes multiple fields atomically in a single round trip.
    r.hset(key, mapping=mapping)

    # Optional TTL: some features are only valid for a while (e.g. "txns in
    # the last hour"). EXPIRE sets the whole hash to auto-delete.
    if ttl_seconds is not None:
        r.expire(key, ttl_seconds)

    print(f"   [WRITE] {len(features)} features written for {entity_type}:{entity_id}")


# ---------------------------------------------------------------------------
# 2. READ SIDE  -  the model serving layer reads features at prediction time
# ---------------------------------------------------------------------------
def read_features(entity_type: str, entity_id: str,
                  feature_names: list[str] | None = None) -> dict:
    """
    Read features for one entity - the hot path, must be milliseconds-fast.

    feature_names=None  -> read ALL features (HGETALL).
    feature_names=[...]  -> read only the ones you need (HMGET), which is
                            cheaper if the entity has many features.
    """
    key = f"features:{entity_type}:{entity_id}"

    if feature_names is None:
        # HGETALL returns every field in the hash.
        raw = r.hgetall(key)
        return {name: json.loads(value) for name, value in raw.items()}
    else:
        # HMGET returns only the requested fields, in order.
        values = r.hmget(key, feature_names)
        return {
            name: (json.loads(value) if value is not None else None)
            for name, value in zip(feature_names, values)
        }


# ---------------------------------------------------------------------------
# 3. A TINY "MODEL" THAT USES THE FEATURES
# ---------------------------------------------------------------------------
def predict_fraud(user_id: str) -> dict:
    """
    A fake fraud model. In reality this would be a trained model; here we
    just apply simple rules to show how features flow into a prediction.
    """
    # Read only the features this model actually needs.
    f = read_features("user", user_id,
                      ["txns_last_hour", "avg_txn_amount", "new_country"])

    # Simple rule-based "score" for illustration.
    score = 0.0
    if f.get("txns_last_hour", 0) > 10:
        score += 0.5
    if f.get("new_country") is True:
        score += 0.4

    return {"user_id": user_id, "fraud_score": round(score, 2), "features_used": f}


# ---------------------------------------------------------------------------
# 4. DEMO  ->  run:  python 04_feature_store_cache.py
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Offline/streaming job pushes fresh features into Redis ---
    print("\n--- Write side: pushing pre-computed features ---")
    write_features(
        "user", "123",
        {
            "avg_txn_amount": 45.20,
            "txns_last_hour": 12,     # unusually high
            "account_age_days": 500,
            "new_country": True,      # suspicious
        },
        ttl_seconds=3600,
    )

    # --- Serving time: model reads features and predicts (fast) ---
    print("\n--- Read side: model serving ---")
    t0 = time.time()
    result = predict_fraud("123")
    print(f"Prediction in {(time.time() - t0) * 1000:.2f} ms")
    print("RESULT:", result)

    # TAKEAWAY:
    # The heavy computation happened OFFLINE. At prediction time we only did
    # fast Redis reads, so the model responds in ~milliseconds. That is what
    # makes real-time ML (fraud, recommendations, ranking) possible.
