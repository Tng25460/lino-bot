# ⚠️ LOCAL ONLY — DO NOT COMMIT
# Clés test (mais considère quand même qu'un chat = compromis)

HELIUS_API_KEY = "20402763-8576-4aa8-9a85-9c1d94383026"

RPC_HTTP = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"
RPC_WS   = f"wss://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"

HELIUS_RPC_URL      = RPC_HTTP
HELIUS_TX_PARSE_URL = f"https://api-mainnet.helius-rpc.com/v0/transactions/?api-key={HELIUS_API_KEY}"
HELIUS_ADDR_TX_URL  = f"https://api-mainnet.helius-rpc.com/v0/addresses/{{address}}/transactions/?api-key={HELIUS_API_KEY}"

JUP_BASE_URL = "https://lite-api.jup.ag"

# Mets ta clé Birdeye ici si tu veux (optionnel)
BIRDEYE_API_KEY = "5feef98f995849888347f9f5c63a3dec"
