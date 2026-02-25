# Testing CLOB Connection & Odds Fetching

This guide shows how to test your CLOB connection and verify you can fetch odds without placing any orders.

## Quick Test (Basic Connection)

Test if your CLOB client can connect:

```bash
cd cli-app
python quick_test_clob.py
```

This will:
- ✓ Check if configuration is set up
- ✓ Test client initialization
- ✓ Test server connection

**Expected output:**
```
============================================================
  Quick CLOB Connection Test
============================================================

✓ Configuration OK
  Initializing CLOB client...
✓ Client initialized
✓ Server status: OK

✓ Basic connection test passed!
```

## Comprehensive Test

For a full test including price/odds fetching:

```bash
# Test with a Polymarket event ID (will fetch token IDs and prices)
python test_clob_connection.py --source-event-id <event_id>

# Or test with a specific token ID (will fetch prices)
python test_clob_connection.py --token-id <token_id>

# Or just test basic connection (read-only)
python test_clob_connection.py
```

### Example: Test with Event ID

```bash
python test_clob_connection.py --source-event-id 0x1234...
```

This will:
1. ✓ Check configuration
2. ✓ Test read-only client (no auth needed)
3. ✓ Test authenticated client
4. ✓ Fetch token IDs from Gamma API
5. ✓ Fetch prices/odds for all outcomes
6. ✓ Test order book fetching

### Example: Test with Token ID

If you already have a token ID:

```bash
python test_clob_connection.py --token-id 71321045679252212594626385532706912750332728571942532289631379312455583992563
```

This will:
1. ✓ Test client connection
2. ✓ Fetch midpoint price
3. ✓ Fetch BUY price
4. ✓ Fetch SELL price
5. ✓ Fetch order book data

## What to Look For

### ✅ Success Indicators

- "✓ Client initialized successfully"
- "✓ Server Status: OK"
- Prices displayed (e.g., "0.4500 (45.00%)")
- Token IDs found and displayed

### ❌ Common Issues

1. **"POLYMARKET_PRIVATE_KEY not set"**
   - Solution: Add `POLYMARKET_PRIVATE_KEY=...` to your `.env` file

2. **"Failed to initialize client"**
   - Check your private key format
   - Check your funder address (if using signature_type 1 or 2)
   - Check network connectivity

3. **"No token IDs found"**
   - The event ID might be invalid
   - The market might not have token IDs yet
   - Try a different event ID

4. **"No prices returned"**
   - Market might be resolved (odds at 0% or 100%)
   - Market might be illiquid
   - Token ID might be invalid

## Getting a Test Event ID

To get a test event ID:

1. Go to Polymarket and find an active market
2. Copy the event ID from the URL or market page
3. Or use the `show-market` command to find one:
   ```bash
   python main.py show-market --slug <market-slug>
   ```

## Next Steps

Once your connection test passes:

1. ✅ Connection works
2. ✅ Can fetch odds
3. ✅ Ready to test order placement (use `place-order` command)

To place a test order:
```bash
python main.py place-order --token-id <id> --amount 0.01 --order-type FOK
```

**Note:** Use a small amount (like $0.01) for testing!

