# CLOB Client Issues Research & Fixes

## Problems Identified

### 1. CLOB Client Initialization Issue

**Current Code (clob_client.py:32-81):**
- Uses `create_or_derive_api_key()` method
- Passes `creds` as constructor parameter
- Does NOT call `set_api_creds()` method

**Documentation Pattern:**
```python
client = ClobClient(
    HOST,
    key=PRIVATE_KEY,
    chain_id=CHAIN_ID,
    signature_type=1,
    funder=FUNDER
)
client.set_api_creds(client.create_or_derive_api_creds())
```

**Issues:**
1. Method name mismatch: `create_or_derive_api_key()` vs `create_or_derive_api_creds()`
2. Missing `set_api_creds()` call - credentials are created but not set on client
3. The client might not be properly authenticated for trading operations

### 2. Token ID Fetching Issues

**Current Implementation (gamma_client.py:92-209):**
- Multiple fallback methods to extract token IDs
- Relies on `clobTokenIds` field from Gamma API
- Falls back to MongoDB if API doesn't have token IDs

**Potential Issues:**
1. Token IDs might not be available in all market responses
2. The `clobTokenIds` field might be named differently
3. Markets might need to be fetched differently to get token IDs
4. The extraction logic might fail silently

**Solution:**
- Add better error handling and logging
- Try CLOB API's `get_simplified_markets()` to find token IDs
- Add validation to ensure token IDs are valid before using

## Fixes Applied

### Fix 1: Updated CLOB Client Initialization ✅

**Changes made:**
1. Updated `_initialize_client()` to follow documentation pattern exactly
2. Try both `create_or_derive_api_creds()` and `create_or_derive_api_key()` for compatibility
3. Call `set_api_creds()` after creating credentials (required for authenticated operations)
4. Initialize client first, then set credentials (matching documentation pattern)

**File:** `cli-app/clob_client.py:32-81`

### Fix 2: Improved Token ID Fetching ✅

**Changes made:**
1. Added CLOB API as fallback source (Method 5) in `get_market_token_ids()`
2. Added `get_token_ids_from_clob()` function to fetch from CLOB simplified markets
3. Added `_extract_token_ids_from_clob_market()` helper function
4. Better error handling with try/except blocks

**Files:**
- `cli-app/gamma_client.py:166-209` - Added CLOB API fallback
- `cli-app/clob_client.py:266-320` - Added CLOB token ID fetching functions

### Fix 3: Added CLI Command for Direct Order Placement ✅

**Changes made:**
1. Added `place-order` command to CLI
2. Supports all order types: GTC, GTD, FOK, FAK
3. Supports market orders (FOK/FAK) and limit orders (GTC/GTD)
4. Updated `place_buy_order()` to handle both market and limit orders correctly

**Files:**
- `cli-app/main.py` - Added command parser and handler
- `cli-app/clob_client.py:197-270` - Updated to support MarketOrderArgs for market orders

**Usage:**
```bash
# Place a limit order (GTC)
python main.py place-order --token-id <id> --amount 1.0 --price 0.45

# Place a market order (FOK)
python main.py place-order --token-id <id> --amount 1.0 --order-type FOK

# Place with market price (limit order)
python main.py place-order --token-id <id> --amount 1.0
```

## Testing

### Test Scripts Created

Two test scripts have been created to verify CLOB connection without placing orders:

1. **`quick_test_clob.py`** - Quick basic connection test
   ```bash
   python quick_test_clob.py
   ```
   - Tests configuration
   - Tests client initialization
   - Tests server connection

2. **`test_clob_connection.py`** - Comprehensive test suite
   ```bash
   # Basic test (read-only operations)
   python test_clob_connection.py
   
   # Test with a source event ID (fetches token IDs and prices)
   python test_clob_connection.py --source-event-id <event_id>
   
   # Test with a specific token ID (fetches prices)
   python test_clob_connection.py --token-id <token_id>
   ```
   - Tests configuration
   - Tests read-only client (no auth)
   - Tests authenticated client
   - Tests token ID fetching from Gamma API
   - Tests price/odds fetching
   - Tests order book fetching
   - Tests CLOB simplified markets

### Testing Checklist

- [ ] Run `quick_test_clob.py` - Basic connection works
- [ ] Run `test_clob_connection.py` - All tests pass
- [ ] CLOB client initializes without errors
- [ ] Can fetch prices using `get_midpoint()` or `get_price()`
- [ ] Can fetch order book data
- [ ] Token IDs are fetched correctly from Gamma API
- [ ] Token IDs can be found via CLOB API as fallback
- [ ] Can place limit orders (GTC) successfully (when ready)
- [ ] Can place market orders (FOK/FAK) successfully (when ready)
- [ ] CLI command works for placing orders (when ready)

## Key Changes Summary

1. **CLOB Client Initialization**: Now properly calls `set_api_creds()` after creating credentials
2. **Token ID Fetching**: Added CLOB API as fallback when Gamma API doesn't have token IDs
3. **Order Placement**: Supports both market orders (MarketOrderArgs) and limit orders (OrderArgs)
4. **CLI Command**: New `place-order` command for direct order placement

## Notes

- The client initialization now tries both method names for compatibility with different library versions
- Market orders (FOK/FAK) use `MarketOrderArgs` and don't require a price
- Limit orders (GTC/GTD) use `OrderArgs` and require a price (or will fetch market price)
- Token ID fetching now has 5 fallback methods for maximum reliability

