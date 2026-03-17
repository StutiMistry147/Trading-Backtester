mtype = { buy, sell, confirmed, filled, rejected, timeout };
chan toExchange = [2] of { mtype, byte, byte };  // msg, price, order_id
chan fromExchange = [2] of { mtype, byte };       // msg, order_id

byte order_counter = 0;
byte pending_orders = 0;
byte fill_count[10] = 0;  // Track fills per order_id (max 10 concurrent orders)

active proctype Trader() {
    byte order_id;
    byte price;
    mtype msg;
    bool order_active = false;
    
    do
    :: !order_active ->
        // Send new order
        order_id = order_counter++;
        price = 100 + (order_id % 20);  // Random-ish price
        printf("Trader: Sending order #%d at price %d\n", order_id, price);
        
        if
        :: toExchange ! buy, price, order_id;
           order_active = true;
           pending_orders++;
        :: toExchange ! sell, price, order_id;
           order_active = true;
           pending_orders++;
        fi;
        
    :: order_active ->
        // Wait for response with timeout
        if
        :: fromExchange ? confirmed, order_id ->
           printf("Trader: Order #%d confirmed\n", order_id);
           
           // Wait for fill
           if
           :: fromExchange ? filled, order_id ->
              printf("Trader: Order #%d filled successfully\n", order_id);
              order_active = false;
              pending_orders--;
              
           :: fromExchange ? rejected, order_id ->
              printf("Trader: Order #%d rejected\n", order_id);
              order_active = false;
              pending_orders--;
              
           :: timeout ->
              printf("Trader: Order #%d timeout - no response\n", order_id);
              order_active = false;
              pending_orders--;
           fi;
           
        :: fromExchange ? rejected, order_id ->
           printf("Trader: Order #%d rejected immediately\n", order_id);
           order_active = false;
           pending_orders--;
           
        :: timeout ->
           printf("Trader: Order #%d timeout - no ack\n", order_id);
           order_active = false;
           pending_orders--;
        fi;
        
        // Small delay between orders
        timeout;
    od;
}

active proctype Exchange() {
    mtype msg;
    byte price;
    byte order_id;
    byte order_book[10];  // Simple order book
    
    do
    :: toExchange ? msg, price, order_id ->
       printf("Exchange: Received order #%d at price %d\n", order_id, price);
       
       // Validate order
       if
       :: price > 0 && price < 200 ->
          fromExchange ! confirmed, order_id;
          
          // Simulate processing delay
          timeout;
          
          // Fill or reject based on market conditions
          if
          :: order_book[order_id % 10] == 0 ->
             order_book[order_id % 10] = price;
             fromExchange ! filled, order_id;
             fill_count[order_id % 10]++;  // Track fills for verification
             printf("Exchange: Order #%d filled\n", order_id);
          :: else ->
             fromExchange ! rejected, order_id;
             printf("Exchange: Order #%d rejected - duplicate ID\n", order_id);
          fi;
          
       :: else ->
          fromExchange ! rejected, order_id;
          printf("Exchange: Order #%d rejected - invalid price\n", order_id);
       fi;
    od;
}

// Verification properties - FIXED with proper assertions

// Property 1: No order can be double-filled (using fill_count)
ltl no_double_fill { 
    [] (forall i in 0..9 : fill_count[i] <= 1)
}

// Property 2: All orders eventually get a response (confirmed or rejected)
ltl all_orders_complete { 
    [] ((toExchange[buy] || toExchange[sell]) -> 
        <> (fromExchange[confirmed] || fromExchange[rejected]))
}

// Property 3: Order count consistency - pending orders never exceed max
ltl order_count_bounded { 
    [] (pending_orders <= 2) 
}

// Property 4: System is live - eventually pending orders are processed
ltl system_liveness {
    [] (pending_orders > 0 -> <> (pending_orders == 0))
}

// Assertion: No deadlock when orders are pending
active proctype DeadlockMonitor() {
    do
    :: atomic {
        // If there are pending orders but no communication possible, assert
        if
        :: pending_orders > 0 && 
           empty(toExchange) && empty(fromExchange) &&
           !toExchange?[buy] && !toExchange?[sell] && 
           !fromExchange?[confirmed] && !fromExchange?[filled] && !fromExchange?[rejected] ->
           assert(false)
        :: else -> skip
        fi
    }
    od;
}

// Monitor process for liveness
active proctype Monitor() {
    do
    :: timeout ->
       printf("Monitor: System heartbeat - pending orders: %d\n", pending_orders);
    od;
}
