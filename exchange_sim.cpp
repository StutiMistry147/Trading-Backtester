#include <iostream>
#include <fstream>
#include <random>
#include <chrono>
#include <thread>
#include <iomanip>
#include <ctime>
#include <atomic>
#include <signal.h>

std::atomic<bool> running{true};

void signal_handler(int) {
    running = false;
}

int main() {
    signal(SIGINT, signal_handler);
    
    double price = 100.0;
    const double MIN_PRICE = 10.0;  // Price floor to prevent negative prices
    
    // Properly seed the random engine
    std::random_device rd;
    std::mt19937 gen(rd());
    std::normal_distribution<double> noise(0, 0.05);
    
    // Use CSV file for simplicity (pipe was causing issues)
    std::ofstream feed("market_data.csv");
    if (!feed) {
        std::cerr << "Failed to open market_data.csv" << std::endl;
        return 1;
    }
    
    feed << "timestamp,ticker,price,volume" << std::endl;
    std::cout << "Market Feed Started... Generating ticks to market_data.csv" << std::endl;
    
    int tick_count = 0;
    while(running) {
        // Add random walk with mean reversion to prevent unbounded movement
        price += noise(gen);
        
        // Mean reversion towards 100
        price = 100.0 + (price - 100.0) * 0.99;
        
        // Ensure price doesn't go below minimum
        if (price < MIN_PRICE) price = MIN_PRICE;
        
        // Format timestamp properly - FIXED: to_time_t instead of to_timestamp
        auto now = std::chrono::system_clock::now();
        auto now_time_t = std::chrono::system_clock::to_time_t(now);
        auto now_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
            now.time_since_epoch()) % 1000;
        
        std::stringstream timestamp;
        timestamp << std::put_time(std::localtime(&now_time_t), "%H:%M:%S")
                  << '.' << std::setfill('0') << std::setw(3) << now_ms.count();
        
        // Add random volume
        std::uniform_int_distribution<int> volume_dist(100, 10000);
        int volume = volume_dist(gen);
        
        feed << timestamp.str() << ",AAPL," << std::fixed << std::setprecision(2) 
             << price << "," << volume << std::endl;
        
        // Flush every 10 ticks for better performance
        if (++tick_count % 10 == 0) {
            feed.flush();
            std::cout << "Tick " << tick_count << ": $" << price << " (vol: " << volume << ")" << std::endl;
        }
        
        std::this_thread::sleep_for(std::chrono::milliseconds(10));  // 10ms ticks for HFT
    }
    
    feed.close();
    std::cout << "\nMarket feed stopped. Generated " << tick_count << " ticks." << std::endl;
    return 0;
}
