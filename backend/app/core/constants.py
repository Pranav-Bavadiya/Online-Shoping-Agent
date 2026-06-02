"""Application-wide constants."""

# Thread
MAX_THREADS_PER_USER = 50
MAX_THREAD_LIST_LIMIT = 50

# Cache
MAX_RAW_PRODUCTS_PER_CACHE = 500
MIN_RAW_PRODUCTS_PER_CACHE = 200
CACHE_KEYWORD_SIMILARITY_THRESHOLD = 0.6

# Search
MAX_SEARCH_RESULTS_RETURNED = 20
MAX_TOOL_ITERATIONS = 30
API_RETRY_ATTEMPTS = 3
API_TIMEOUT_SECONDS = 10.0

# LLM
MAX_CONTEXT_MESSAGES = 8
QUERY_CONTEXT_MESSAGES = 5
DISAMBIGUATION_CONTEXT_MESSAGES = 3
TOOL_CONTEXT_MESSAGES = 8

# Ranking
FEEDBACK_CLICK_BOOST = 0.05
FEEDBACK_LIKE_BOOST = 0.10
FEEDBACK_IGNORE_PENALTY = -0.03

# Diversity
MIN_BRANDS_IN_RESULTS = 3
MAX_SAME_BRAND_PERCENT = 0.40

# Intent labels
INTENT_SEARCH = "search"
INTENT_CHAT = "chat"

# Cache decisions
DECISION_REUSE = "reuse"
DECISION_PARTIAL = "partial"
DECISION_NEW = "new"

# Feedback actions
FEEDBACK_CLICK = "click"
FEEDBACK_LIKE = "like"
FEEDBACK_IGNORE = "ignore"

# Tool names
TOOL_PRODUCT_DETAIL = "product_detail"
TOOL_SEARCH = "search_tool"

# Message roles
ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"

# New tool names (commerce)
TOOL_ADD_TO_CART      = "add_to_cart"
TOOL_REMOVE_FROM_CART = "remove_from_cart"
TOOL_SHOW_CART        = "show_cart"
TOOL_UPDATE_CART_QTY  = "update_cart_quantity"
TOOL_CLEAR_CART       = "clear_cart"
TOOL_CHANGE_MARKETS   = "change_marketplaces"
TOOL_START_CHECKOUT   = "start_checkout"
TOOL_SELECT_ITEMS     = "select_checkout_items"
TOOL_SELECT_ADDRESS   = "select_address"
TOOL_ADD_ADDRESS      = "add_address"
TOOL_CREATE_PAYMENT   = "create_payment"
TOOL_CONFIRM_PAYMENT  = "confirm_payment"
TOOL_BUY_NOW          = "buy_now"

# Marketplaces
MARKETPLACE_LOCAL = "local"
MARKETPLACE_EBAY  = "ebay"
MARKETPLACE_MOCK  = "mock"
ALL_MARKETPLACES  = [MARKETPLACE_LOCAL, MARKETPLACE_EBAY, MARKETPLACE_MOCK]

# Order statuses
ORDER_PENDING_PAYMENT = "PENDING_PAYMENT"
ORDER_PAID            = "PAID"
ORDER_DISPATCHED      = "DISPATCHED"
ORDER_COMPLETED       = "COMPLETED"
ACTIVE_ORDER_STATUSES = [ORDER_PENDING_PAYMENT, ORDER_PAID]

# User roles
ROLE_CUSTOMER = "customer"
ROLE_SELLER   = "seller"

# Checkout steps
CHECKOUT_STEP_INIT    = "init"
CHECKOUT_STEP_ITEMS   = "items_selected"
CHECKOUT_STEP_ADDRESS = "address_selected"
CHECKOUT_STEP_PAYMENT = "payment_created"
CHECKOUT_STEP_DONE    = "done"
