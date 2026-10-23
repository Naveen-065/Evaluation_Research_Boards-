#define _POSIX_C_SOURCE 200809L

#include <arpa/inet.h>
#include <errno.h>
#include <netinet/in.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <sys/types.h>
#include <unistd.h>

#include "zesEdacV130.h"
#include "zes_protocol.h"

#define DEFAULT_BIND_ADDRESS "127.0.0.1"
#define DEFAULT_PORT 9106u
#define LISTEN_BACKLOG 8
#define MAX_VERSION_TEXT 240u
#define CLIENT_IO_TIMEOUT_SECONDS 30

static volatile sig_atomic_t running = 1;

static void stop_server(int signal_number)
{
    (void)signal_number;
    running = 0;
}

static uint32_t read_u32_be(const uint8_t *source)
{
    return ((uint32_t)source[0] << 24) |
           ((uint32_t)source[1] << 16) |
           ((uint32_t)source[2] << 8) |
           (uint32_t)source[3];
}

static void write_u32_be(uint8_t *destination, uint32_t value)
{
    destination[0] = (uint8_t)(value >> 24);
    destination[1] = (uint8_t)(value >> 16);
    destination[2] = (uint8_t)(value >> 8);
    destination[3] = (uint8_t)value;
}

/* Returns 1 on success, 0 on clean EOF before any byte, and -1 on error. */
static int read_exact(int fd, void *destination, size_t length)
{
    uint8_t *cursor = (uint8_t *)destination;
    size_t received = 0;

    while (received < length) {
        ssize_t count = recv(fd, cursor + received, length - received, 0);
        if (count == 0) {
            return received == 0 ? 0 : -1;
        }
        if (count < 0) {
            if (errno == EINTR) {
                continue;
            }
            return -1;
        }
        received += (size_t)count;
    }
    return 1;
}

static int write_exact(int fd, const void *source, size_t length)
{
    const uint8_t *cursor = (const uint8_t *)source;
    size_t sent = 0;

    while (sent < length) {
        ssize_t count = send(fd, cursor + sent, length - sent, MSG_NOSIGNAL);
        if (count < 0) {
            if (errno == EINTR) {
                continue;
            }
            return -1;
        }
        if (count == 0) {
            return -1;
        }
        sent += (size_t)count;
    }
    return 0;
}

static int send_response(int fd,
                         uint8_t opcode,
                         uint32_t request_id,
                         uint32_t status,
                         const void *body,
                         uint32_t body_length)
{
    uint8_t header[ZES_PROTOCOL_HEADER_SIZE] = {0};
    uint8_t status_bytes[4];
    uint32_t payload_length = body_length + 4u;

    memcpy(header, ZES_PROTOCOL_MAGIC, ZES_PROTOCOL_MAGIC_SIZE);
    header[4] = ZES_PROTOCOL_VERSION;
    header[5] = (uint8_t)(opcode | ZES_RESPONSE_BIT);
    write_u32_be(header + 8, payload_length);
    write_u32_be(header + 12, request_id);
    write_u32_be(status_bytes, status);

    if (write_exact(fd, header, sizeof(header)) != 0 ||
        write_exact(fd, status_bytes, sizeof(status_bytes)) != 0) {
        return -1;
    }
    if (body_length != 0u && write_exact(fd, body, body_length) != 0) {
        return -1;
    }
    return 0;
}

static int handle_info(int fd, uint8_t opcode, uint32_t request_id)
{
    uint8_t body[8u + MAX_VERSION_TEXT];
    const char *version = getVersion();
    size_t version_length = version == NULL ? 0u : strlen(version);

    if (version_length > MAX_VERSION_TEXT) {
        version_length = MAX_VERSION_TEXT;
    }
    write_u32_be(body, ZES_DATA_BYTES);
    write_u32_be(body + 4, ZES_PARITY_BYTES);
    if (version_length != 0u) {
        memcpy(body + 8, version, version_length);
    }
    return send_response(fd, opcode, request_id, ZES_STATUS_OK,
                         body, (uint32_t)(8u + version_length));
}

static int handle_encode(int fd,
                         uint8_t opcode,
                         uint32_t request_id,
                         const uint8_t *payload)
{
    int data[ZES_DATA_WORDS];
    int parity[ZES_PARITY_WORDS];

    memcpy(data, payload, ZES_DATA_BYTES);
    memset(parity, 0, sizeof(parity));
    encodeAllRowColPariBits(data, parity);
    return send_response(fd, opcode, request_id, ZES_STATUS_OK,
                         parity, ZES_PARITY_BYTES);
}

static int handle_check_repair(int fd,
                               uint8_t opcode,
                               uint32_t request_id,
                               const uint8_t *payload)
{
    int data[ZES_DATA_WORDS];
    int parity[ZES_PARITY_WORDS];
    uint8_t body[4u + ZES_DATA_BYTES];
    uint32_t threshold = read_u32_be(payload);
    int decoder_result;

    if (threshold == 0u || threshold > 8192u) {
        return send_response(fd, opcode, request_id,
                             ZES_STATUS_BAD_ARGUMENT, NULL, 0u);
    }

    memcpy(data, payload + 4u, ZES_DATA_BYTES);
    memcpy(parity, payload + 4u + ZES_DATA_BYTES, ZES_PARITY_BYTES);
    decoder_result = decodeAndCorrectData(data, parity, (int)threshold);

    write_u32_be(body, (uint32_t)decoder_result);
    memcpy(body + 4u, data, ZES_DATA_BYTES);
    return send_response(fd, opcode, request_id, ZES_STATUS_OK,
                         body, sizeof(body));
}

static int serve_client(int client_fd, unsigned long max_requests)
{
    unsigned long request_count = 0;

    while (running && (max_requests == 0ul || request_count < max_requests)) {
        uint8_t header[ZES_PROTOCOL_HEADER_SIZE];
        uint8_t *payload = NULL;
        uint32_t payload_length;
        uint32_t request_id;
        uint8_t opcode;
        int read_result = read_exact(client_fd, header, sizeof(header));
        int response_result = 0;

        if (read_result == 0) {
            return 0;
        }
        if (read_result < 0) {
            return -1;
        }

        opcode = header[5];
        payload_length = read_u32_be(header + 8);
        request_id = read_u32_be(header + 12);

        if (payload_length > ZES_PROTOCOL_MAX_PAYLOAD) {
            fprintf(stderr, "request %u rejected: payload too large\n", request_id);
            return -1;
        }
        if (payload_length != 0u) {
            payload = (uint8_t *)malloc(payload_length);
            if (payload == NULL) {
                send_response(client_fd, opcode, request_id,
                              ZES_STATUS_INTERNAL, NULL, 0u);
                return -1;
            }
            if (read_exact(client_fd, payload, payload_length) != 1) {
                free(payload);
                return -1;
            }
        }

        if (memcmp(header, ZES_PROTOCOL_MAGIC, ZES_PROTOCOL_MAGIC_SIZE) != 0) {
            response_result = send_response(client_fd, opcode, request_id,
                                            ZES_STATUS_BAD_MAGIC, NULL, 0u);
        } else if (header[4] != ZES_PROTOCOL_VERSION) {
            response_result = send_response(client_fd, opcode, request_id,
                                            ZES_STATUS_BAD_VERSION, NULL, 0u);
        } else if (header[6] != 0u || header[7] != 0u) {
            response_result = send_response(client_fd, opcode, request_id,
                                            ZES_STATUS_BAD_ARGUMENT, NULL, 0u);
        } else if (opcode == ZES_OP_INFO) {
            response_result = payload_length == 0u
                ? handle_info(client_fd, opcode, request_id)
                : send_response(client_fd, opcode, request_id,
                                ZES_STATUS_BAD_LENGTH, NULL, 0u);
        } else if (opcode == ZES_OP_ENCODE) {
            response_result = payload_length == ZES_DATA_BYTES
                ? handle_encode(client_fd, opcode, request_id, payload)
                : send_response(client_fd, opcode, request_id,
                                ZES_STATUS_BAD_LENGTH, NULL, 0u);
        } else if (opcode == ZES_OP_CHECK_REPAIR) {
            response_result = payload_length == (4u + ZES_DATA_BYTES + ZES_PARITY_BYTES)
                ? handle_check_repair(client_fd, opcode, request_id, payload)
                : send_response(client_fd, opcode, request_id,
                                ZES_STATUS_BAD_LENGTH, NULL, 0u);
        } else {
            response_result = send_response(client_fd, opcode, request_id,
                                            ZES_STATUS_BAD_OPCODE, NULL, 0u);
        }

        free(payload);
        if (response_result != 0) {
            return -1;
        }
        request_count++;
    }
    return 0;
}

static void usage(const char *program)
{
    fprintf(stderr,
            "Usage: %s [--bind IPv4] [--port 1..65535] [--once] "
            "[--max-requests N]\n",
            program);
}

int main(int argc, char **argv)
{
    const char *bind_address = DEFAULT_BIND_ADDRESS;
    uint32_t port = DEFAULT_PORT;
    unsigned long max_requests = 0ul;
    int once = 0;
    int server_fd;
    int reuse = 1;
    struct sockaddr_in address;
    struct sigaction action;

    for (int index = 1; index < argc; index++) {
        if (strcmp(argv[index], "--bind") == 0 && index + 1 < argc) {
            bind_address = argv[++index];
        } else if (strcmp(argv[index], "--port") == 0 && index + 1 < argc) {
            char *end = NULL;
            unsigned long value = strtoul(argv[++index], &end, 10);
            if (end == NULL || *end != '\0' || value == 0ul || value > 65535ul) {
                usage(argv[0]);
                return 2;
            }
            port = (uint32_t)value;
        } else if (strcmp(argv[index], "--max-requests") == 0 && index + 1 < argc) {
            char *end = NULL;
            max_requests = strtoul(argv[++index], &end, 10);
            if (end == NULL || *end != '\0') {
                usage(argv[0]);
                return 2;
            }
        } else if (strcmp(argv[index], "--once") == 0) {
            once = 1;
        } else {
            usage(argv[0]);
            return 2;
        }
    }

    if (sizeof(int) != 4u || intDataBufferSize() != (int)ZES_DATA_WORDS ||
        intParityBufferSize() != (int)ZES_PARITY_WORDS) {
        fprintf(stderr,
                "ZES library geometry mismatch: int=%zu data_words=%d parity_words=%d\n",
                sizeof(int), intDataBufferSize(), intParityBufferSize());
        return 3;
    }

    memset(&action, 0, sizeof(action));
    action.sa_handler = stop_server;
    sigemptyset(&action.sa_mask);
    sigaction(SIGINT, &action, NULL);
    sigaction(SIGTERM, &action, NULL);

    server_fd = socket(AF_INET, SOCK_STREAM, 0);
    if (server_fd < 0) {
        perror("socket");
        return 4;
    }
    setsockopt(server_fd, SOL_SOCKET, SO_REUSEADDR, &reuse, sizeof(reuse));

    memset(&address, 0, sizeof(address));
    address.sin_family = AF_INET;
    address.sin_port = htons((uint16_t)port);
    if (inet_pton(AF_INET, bind_address, &address.sin_addr) != 1) {
        fprintf(stderr, "invalid IPv4 bind address: %s\n", bind_address);
        close(server_fd);
        return 2;
    }
    if (bind(server_fd, (struct sockaddr *)&address, sizeof(address)) != 0) {
        perror("bind");
        close(server_fd);
        return 4;
    }
    if (listen(server_fd, LISTEN_BACKLOG) != 0) {
        perror("listen");
        close(server_fd);
        return 4;
    }

    fprintf(stderr, "zes-edac-relay %s listening on %s:%u\n",
            getVersion(), bind_address, port);

    while (running) {
        struct sockaddr_in peer;
        socklen_t peer_length = sizeof(peer);
        int client_fd = accept(server_fd, (struct sockaddr *)&peer, &peer_length);
        char peer_text[INET_ADDRSTRLEN] = "unknown";
        struct timeval client_timeout = {CLIENT_IO_TIMEOUT_SECONDS, 0};

        if (client_fd < 0) {
            if (errno == EINTR) {
                continue;
            }
            perror("accept");
            break;
        }
        if (setsockopt(client_fd, SOL_SOCKET, SO_RCVTIMEO,
                       &client_timeout, sizeof(client_timeout)) != 0 ||
            setsockopt(client_fd, SOL_SOCKET, SO_SNDTIMEO,
                       &client_timeout, sizeof(client_timeout)) != 0) {
            perror("client timeout");
            close(client_fd);
            continue;
        }
        inet_ntop(AF_INET, &peer.sin_addr, peer_text, sizeof(peer_text));
        fprintf(stderr, "client connected: %s\n", peer_text);
        if (serve_client(client_fd, max_requests) != 0) {
            fprintf(stderr, "client session ended with an I/O error\n");
        }
        close(client_fd);
        if (once) {
            break;
        }
    }

    close(server_fd);
    return 0;
}
