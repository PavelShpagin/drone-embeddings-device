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
#include <errno.h>
#include <random>
#include <sstream>
#include <iomanip>

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
    const std::string LOG_FILE = "data/reader.txt";
    double init_lat = 50.4162;
    double init_lng = 30.8906;
    int init_meters = 1000;
    std::chrono::steady_clock::time_point last_frame_time;
    bool init_map_requested;
    
public:
    DeviceReader(double lat, double lng, int meters) : localizer_ready(false), current_frame_index(0), init_lat(lat), init_lng(lng), init_meters(meters), init_map_requested(false) {
        setupSockets();
        loadStreamFiles();
        clearLogFile();
        last_frame_time = std::chrono::steady_clock::now();
    }
    
    void setupSockets() {
        // Create TCP sockets
        init_map_sock = -1; // created on demand in sendInitMapRequest
        fetch_gps_sock = -1; // created per request in sendFetchGpsRequest
        
        // Setup addresses
        init_map_addr.sin_family = AF_INET;
        init_map_addr.sin_port = htons(18001);
        inet_pton(AF_INET, "127.0.0.1", &init_map_addr.sin_addr);
        
        fetch_gps_addr.sin_family = AF_INET;
        fetch_gps_addr.sin_port = htons(18002);
        inet_pton(AF_INET, "127.0.0.1", &fetch_gps_addr.sin_addr);
        
        std::cout << "TCP sockets configured for localizer communication" << std::endl;
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
        std::string request = std::string("{") +
            "\"lat\": " + std::to_string(init_lat) + "," +
            "\"lng\": " + std::to_string(init_lng) + "," +
            "\"meters\": " + std::to_string(init_meters) + "," +
            "\"mode\": \"device\"" +
        "}";
        
        // Create a fresh socket each attempt
        if (init_map_sock >= 0) close(init_map_sock);
        init_map_sock = socket(AF_INET, SOCK_STREAM, 0);
        if (init_map_sock < 0) {
            std::cerr << "Socket creation failed for init_map" << std::endl;
            return;
        }

        // Connect and send TCP request
        if (connect(init_map_sock, (struct sockaddr*)&init_map_addr, sizeof(init_map_addr)) < 0) {
            std::cerr << "Failed to connect to init_map server (port 18001). Is localizer running?" << std::endl;
            close(init_map_sock);
            init_map_sock = -1;
            init_map_requested = false; // Allow retry
            return;
        }
        
        send(init_map_sock, request.c_str(), request.length(), 0);
        std::cout << "Sent init_map request via TCP" << std::endl;
        init_map_requested = true;
    }
    
    void checkInitMapResponse() {
        if (init_map_sock < 0) return; // not connected
        char buffer[4096];
        ssize_t bytes = recv(init_map_sock, buffer, sizeof(buffer)-1, MSG_DONTWAIT);
        
        if (bytes < 0) {
            if (errno == EAGAIN || errno == EWOULDBLOCK) {
                // No data yet; try again later without blocking
                return;
            } else {
                std::cerr << "Error receiving init_map response: errno=" << errno << std::endl;
                return;
            }
        }

        if (bytes > 0) {
            buffer[bytes] = '\0';
            std::string response(buffer);
            
            // Parse session_id from JSON response - debug print first
            std::cout << "Raw response: " << response << std::endl;
            
            size_t start = response.find("\"session_id\": \"");
            if (start != std::string::npos) {
                start += 15;  // Length of "session_id": "
                size_t end = response.find("\"", start);
                if (end != std::string::npos) {
                    session_id = response.substr(start, end - start);
                } else {
                    std::cout << "End quote not found" << std::endl;
                }
            } else {
                std::cout << "session_id field not found. Response: " << response << std::endl;
            }
            
            if (!session_id.empty()) {
                localizer_ready = true;
                close(init_map_sock); // Close TCP connection
                std::cout << "Received session_id: " << session_id << std::endl;
                
                std::ofstream log(LOG_FILE, std::ios::app);
                log << "Session initialized: " << session_id << std::endl;
                log.close();
                init_map_sock = -1;
            }
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
        
        // Create new socket for each request
        int new_sock = socket(AF_INET, SOCK_STREAM, 0);
        if (connect(new_sock, (struct sockaddr*)&fetch_gps_addr, sizeof(fetch_gps_addr)) < 0) {
            std::cerr << "Failed to connect to fetch_gps server (port 18002). Is localizer running?" << std::endl;
            close(new_sock);
            return;
        }
        
        // Send request size first, then request
        std::string size_str = std::to_string(request.length());
        size_str.resize(4, ' '); // Pad to 4 bytes
        send(new_sock, size_str.c_str(), 4, 0);
        send(new_sock, request.c_str(), request.length(), 0);
        
        fetch_gps_sock = new_sock; // Store for response
        localizer_ready = false;
        std::cout << "Sent fetch_gps request for: " << image_path << std::endl;
    }
    
    void checkFetchGpsResponse() {
        char buffer[8192];
        ssize_t bytes = recv(fetch_gps_sock, buffer, sizeof(buffer)-1, MSG_DONTWAIT);
        
        if (bytes > 0) {
            buffer[bytes] = '\0';
            std::string response(buffer);
            
            localizer_ready = true;
            close(fetch_gps_sock); // Close TCP connection
            
            // Log GPS result
            std::ofstream log(LOG_FILE, std::ios::app);
            log << "Frame " << current_frame_index-1 << ": " << response << std::endl;
            log.close();
            
            std::cout << "Received GPS response: " << response.substr(0, 100) << "..." << std::endl;
        }
    }
    
    void run() {
        std::cout << "Starting DeviceReader main loop" << std::endl;
        std::cout << "Stream files loaded: " << stream_files.size() << std::endl;
        
        int loop_count = 0;
        while (true) {
            loop_count++;
            if (loop_count % 1000 == 0) {
                std::cout << "Main loop iteration " << loop_count << ", session_id=" << (session_id.empty() ? "empty" : session_id.substr(0,8)) << ", init_requested=" << init_map_requested << std::endl;
            }
            
            // Always check for responses first (non-blocking)
            if (session_id.empty()) {
                checkInitMapResponse();
            } else {
                if (!localizer_ready) {
                    checkFetchGpsResponse();
                }
            }

            // Pace at ~1 FPS: only act when 1s elapsed since last frame decision
            auto now = std::chrono::steady_clock::now();
            auto since_last = std::chrono::duration_cast<std::chrono::milliseconds>(now - last_frame_time).count();
            if (since_last >= 1000) {
                if (session_id.empty()) {
                    if (!init_map_requested) {
                        std::cout << "Sending init_map request..." << std::endl;
                        sendInitMapRequest();
                    } else {
                        std::cout << "Waiting for init_map response..." << std::endl;
                    }
                }
                if (!session_id.empty() && current_frame_index < stream_files.size()) {
                    if (localizer_ready) {
                        // Send next frame
                        std::cout << "Processing frame " << current_frame_index << "/" << stream_files.size() << std::endl;
                        sendFetchGpsRequest();
                    } else {
                        // Drop current frame if localizer busy
                        std::cout << "Dropping frame " << current_frame_index << " (localizer busy)" << std::endl;
                        std::ofstream log(LOG_FILE, std::ios::app);
                        log << "Dropped frame " << current_frame_index << " (localizer busy)" << std::endl;
                        log.close();
                        current_frame_index++;
                    }
                }
                last_frame_time = now;
            }
            
            // Short sleep to avoid busy loop
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
            
            // Exit condition
            if (!session_id.empty() && current_frame_index >= stream_files.size() && localizer_ready) {
                std::cout << "Processing complete - all " << stream_files.size() << " frames processed" << std::endl;
                break;
            }
            
            // Safety exit after reasonable time  
            static auto start_time = std::chrono::steady_clock::now();
            auto elapsed = std::chrono::duration_cast<std::chrono::seconds>(now - start_time).count();
            if (elapsed > 60) { // 1 minute max
                std::cout << "Timeout reached after " << elapsed << " seconds, exiting" << std::endl;
                break;
            }
        }
    }
    
    ~DeviceReader() {
        if (init_map_sock >= 0) close(init_map_sock);
        if (fetch_gps_sock >= 0) close(fetch_gps_sock);
    }
};

int main(int argc, char* argv[]) {
    std::cout << "DeviceReader starting..." << std::endl;

    double lat = 50.4162;
    double lng = 30.8906;
    int meters = 1000;
    for (int i = 1; i < argc; ++i) {
        if ((std::string)argv[i] == "--lat" && i + 1 < argc) {
            lat = std::stod(argv[++i]);
        } else if ((std::string)argv[i] == "--lng" && i + 1 < argc) {
            lng = std::stod(argv[++i]);
        } else if ((std::string)argv[i] == "--meters" && i + 1 < argc) {
            meters = std::stoi(argv[++i]);
        }
    }

    DeviceReader reader(lat, lng, meters);
    reader.run();
    
    std::cout << "DeviceReader finished" << std::endl;
    return 0;
}