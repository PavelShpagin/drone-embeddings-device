#include <iostream>
#include <fstream>
#include <string>
#include <chrono>
#include <thread>
#include <filesystem>
#include <vector>
#include <algorithm>
#include <cstring>
#include <sys/socket.h>
#include <arpa/inet.h>
#include <unistd.h>
#include <fcntl.h>

class DeviceReader {
private:
    int init_map_sock;
    int fetch_gps_sock;
    struct sockaddr_in init_map_addr;
    struct sockaddr_in fetch_gps_addr;
    
    std::string session_id;
    bool localizer_ready;
    int current_frame_index;
    std::vector<std::string> stream_files;
    
    const std::string STREAM_DIR = "data/stream";
    const std::string LOG_FILE = "data/reader.log";
    
public:
    DeviceReader() : localizer_ready(false), current_frame_index(0) {
        setupSockets();
        loadStreamFiles();
        clearLogFile();
    }
    
    void setupSockets() {
        // Create sockets
        init_map_sock = socket(AF_INET, SOCK_DGRAM, 0);
        fetch_gps_sock = socket(AF_INET, SOCK_DGRAM, 0);
        
        if (init_map_sock < 0 || fetch_gps_sock < 0) {
            std::cerr << "Socket creation failed" << std::endl;
            exit(1);
        }
        
        // Set non-blocking
        fcntl(init_map_sock, F_SETFL, O_NONBLOCK);
        fcntl(fetch_gps_sock, F_SETFL, O_NONBLOCK);
        
        // Setup addresses
        init_map_addr.sin_family = AF_INET;
        init_map_addr.sin_port = htons(8001);
        inet_pton(AF_INET, "127.0.0.1", &init_map_addr.sin_addr);
        
        fetch_gps_addr.sin_family = AF_INET;
        fetch_gps_addr.sin_port = htons(8002);
        inet_pton(AF_INET, "127.0.0.1", &fetch_gps_addr.sin_addr);
        
        std::cout << "Sockets configured for localizer communication" << std::endl;
    }
    
    void loadStreamFiles() {
        for (const auto& entry : std::filesystem::directory_iterator(STREAM_DIR)) {
            if (entry.path().extension() == ".jpg") {
                stream_files.push_back(entry.path().string());
            }
        }
        std::sort(stream_files.begin(), stream_files.end());
        std::cout << "Loaded " << stream_files.size() << " stream files" << std::endl;
    }
    
    void clearLogFile() {
        std::ofstream log(LOG_FILE);
        log << "DeviceReader started at " << getCurrentTimestamp() << std::endl;
        log.close();
    }
    
    std::string getCurrentTimestamp() {
        auto now = std::chrono::system_clock::now();
        auto time_t = std::chrono::system_clock::to_time_t(now);
        return std::ctime(&time_t);
    }
    
    void sendInitMapRequest() {
        std::string request = R"({
            "lat": 50.4162,
            "lng": 30.8906,
            "meters": 1000,
            "mode": "device"
        })";
        
        sendto(init_map_sock, request.c_str(), request.length(), 0,
               (struct sockaddr*)&init_map_addr, sizeof(init_map_addr));
        
        std::cout << "Sent init_map request" << std::endl;
    }
    
    void checkInitMapResponse() {
        char buffer[4096];
        ssize_t bytes = recv(init_map_sock, buffer, sizeof(buffer)-1, 0);
        
        if (bytes > 0) {
            buffer[bytes] = '\0';
            std::string response(buffer);
            
            // Parse session_id from JSON response
            size_t start = response.find("\"session_id\":\"") + 14;
            size_t end = response.find("\"", start);
            session_id = response.substr(start, end - start);
            
            localizer_ready = true;
            std::cout << "Received session_id: " << session_id << std::endl;
            
            std::ofstream log(LOG_FILE, std::ios::app);
            log << "Session initialized: " << session_id << std::endl;
            log.close();
        }
    }
    
    void sendFetchGpsRequest() {
        if (current_frame_index >= stream_files.size()) {
            std::cout << "All frames processed" << std::endl;
            return;
        }
        
        std::string image_path = stream_files[current_frame_index];
        current_frame_index++;
        
        std::string request = "{"
            "\"session_id\":\"" + session_id + "\","
            "\"image_path\":\"" + image_path + "\""
            "}";
        
        sendto(fetch_gps_sock, request.c_str(), request.length(), 0,
               (struct sockaddr*)&fetch_gps_addr, sizeof(fetch_gps_addr));
        
        localizer_ready = false;
        std::cout << "Sent fetch_gps request for: " << image_path << std::endl;
    }
    
    void checkFetchGpsResponse() {
        char buffer[8192];
        ssize_t bytes = recv(fetch_gps_sock, buffer, sizeof(buffer)-1, 0);
        
        if (bytes > 0) {
            buffer[bytes] = '\0';
            std::string response(buffer);
            
            localizer_ready = true;
            
            // Log GPS result
            std::ofstream log(LOG_FILE, std::ios::app);
            log << "Frame " << current_frame_index-1 << ": " << response << std::endl;
            log.close();
            
            std::cout << "Received GPS response: " << response.substr(0, 100) << "..." << std::endl;
        }
    }
    
    void run() {
        std::cout << "Starting DeviceReader main loop" << std::endl;
        
        // Send initial init_map request
        sendInitMapRequest();
        
        while (true) {
            // Check for init_map response if no session yet
            if (session_id.empty()) {
                checkInitMapResponse();
            }
            // Process stream if localizer is ready and session exists
            else if (localizer_ready && current_frame_index < stream_files.size()) {
                sendFetchGpsRequest();
            }
            // Check for fetch_gps responses
            else if (!localizer_ready) {
                checkFetchGpsResponse();
            }
            
            // Sleep 1ms as specified
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
            
            // Exit condition
            if (!session_id.empty() && current_frame_index >= stream_files.size() && localizer_ready) {
                std::cout << "Processing complete" << std::endl;
                break;
            }
        }
    }
    
    ~DeviceReader() {
        close(init_map_sock);
        close(fetch_gps_sock);
    }
};

int main() {
    std::cout << "DeviceReader starting..." << std::endl;
    
    DeviceReader reader;
    reader.run();
    
    std::cout << "DeviceReader finished" << std::endl;
    return 0;
}