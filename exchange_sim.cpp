#include <iostream>
#include <fstream>
#include <random>
#include <chrono>
#include <iomanip>
#include <ctime>
#include <atomic>
#include <signal.h>
#include <sstream>
#include <unistd.h>  // For usleep() - works on Mac/Linux/WSL

std::atomic<bool> running{true};

void signal_handler(int) {
    running = false;
}

int main() {
    signal(SIGINT, signal_handler);

    double price = 100.0;
    const double MIN_PRICE = 10.0;
    const double MAX_PRICE = 500.0;

    std::random_device rd;
    std::mt19937 gen(rd());
    std::normal_distribution<double> noise(0, 0.05);
    std::uniform_real_distribution<double> volatility_shock(0.5, 1.5);

    std::ofstream feed("market_data.csv");
    if (!feed) {
        std::cerr << "Failed to open market_data.csv" << std::endl;
        return 1;
    }

    feed << "timestamp,ticker,price,volume" << std::endl;
    std::cout << "Market Feed Started... Generating ticks to market_data.csv" << std::endl;

    int tick_count = 0;
    double vol_regime = 1.0;
    
    while(running) {
        // Occasionally change volatility regime
        if (tick_count % 1000 == 0) {
            vol_regime = volatility_shock(gen);
        }
        
        // Add random walk with volatility regime
        price += noise(gen) * vol_regime;

        // Mean reversion towards 100
        price = 100.0 + (price - 100.0) * 0.99;

        // Ensure price stays within bounds
        if (price < MIN_PRICE) price = MIN_PRICE;
        if (price > MAX_PRICE) price = MAX_PRICE;

        auto now = std::chrono::system_clock::now();
        auto now_time_t = std::chrono::system_clock::to_time_t(now);
        auto now_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
            now.time_since_epoch()) % 1000;

        std::stringstream timestamp;
        timestamp << std::put_time(std::localtime(&now_time_t), "%H:%M:%S")
                  << '.' << std::setfill('0') << std::setw(3) << now_ms.count();

        std::uniform_int_distribution<int> volume_dist(100, 10000);
        int volume = volume_dist(gen);
        
        // Add occasional volume spikes
        if (tick_count % 500 == 0) {
            volume *= 5;
        }

        feed << timestamp.str() << ",AAPL," << std::fixed << std::setprecision(2) 
             << price << "," << volume << std::endl;

        if (++tick_count % 10 == 0) {
            feed.flush();
            std::cout << "Tick " << tick_count << ": $" << price 
                      << " (vol: " << volume << ", regime: " << vol_regime << ")" << std::endl;
        }

        usleep(10000);  // 10,000 microseconds = 10 milliseconds
    }

    feed.close();
    std::cout << "\nMarket feed stopped. Generated " << tick_count << " ticks." << std::endl;
    return 0;
}
