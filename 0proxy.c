/* 0proxy -- a 0MQ wrapper for stdin/stdout. */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <signal.h>
#include <errno.h>
#include <zmq.h>

#if ZMQ_VERSION_MAJOR == 2
#define zmq_msg_send(msg,sock,opt) zmq_send(sock,msg,opt)
#define zmq_msg_recv(msg,sock,opt) zmq_recv(sock,msg,opt)
#define zmq_ctx_new() zmq_init(1)
#define zmq_ctx_destroy(ctx) zmq_term(ctx)
#endif

static void *context;
static void *sock;

void die(void)
{
	if (sock) zmq_close(sock);
	zmq_ctx_destroy(context);
	exit(1);
}

void fatal(const char *func)
{
	fprintf(stderr, "*** 0proxy: %s failed (%s)\n", func, zmq_strerror(errno));
	die();
}

void onsignal(int sig)
{
	(void) sig;
	if (sig == SIGPIPE) {
		fprintf(stderr, "*** 0proxy: stdout is closed\n");
	} else {
		fprintf(stderr, "*** 0proxy: forced termination\n");
	}
	die();
}

int main(int argc, char **argv)
{
	enum { UNKNOWN, INPUT, OUTPUT } mode = UNKNOWN;
	char *endpoint = argv[1];
	zmq_pollitem_t items[1];

	if (strcmp(argv[0], "0in") == 0) {
		mode = INPUT;
	} else if (strcmp(argv[0], "0out") == 0) {
		mode = OUTPUT;
	} else if (endpoint) {
		if (strcmp(endpoint, "-i") == 0) {
			mode = INPUT;
			endpoint = argv[2];
		} else if (strcmp(endpoint, "-o") == 0) {
			mode = OUTPUT;
			endpoint = argv[2];
		}
	}

	if (!endpoint || mode == UNKNOWN) {
		fprintf(stderr, "Usage: %s {-i|-o} <endpoint>\n", argv[0]);
		fprintf(stderr, "Usage: 0in <endpoint>\n");
		fprintf(stderr, "Usage: 0out <endpoint>\n");
		return 1;
	}

	context = zmq_ctx_new();
	if (!context) fatal("zmq_ctx_new");

	signal(SIGPIPE, onsignal);
	signal(SIGINT, onsignal);
	signal(SIGTERM, onsignal);

	if (mode == INPUT) {
		int val = 0;
		sock = zmq_socket(context, ZMQ_REP);
		if (!sock) fatal("zmq_socket");
		if (zmq_bind(sock, endpoint)) fatal("zmq_bind");
		if (zmq_setsockopt(sock, ZMQ_LINGER, &val, sizeof val)) fatal("zmq_setsockopt(ZMQ_LINGER)");

		items[0].socket = sock;
		items[0].events = ZMQ_POLLIN;
		while (1) {
			zmq_msg_t msg;
			char *p, *pend;

			int rc = zmq_poll(items, 1, -1);
			if (rc < 0) fatal("zmq_poll");

			if (zmq_msg_init(&msg)) fatal("zmq_msg_init");
			if (zmq_msg_recv(&msg, sock, 0) < 0) fatal("zmq_msg_recv");
			p = zmq_msg_data(&msg);
			pend = p + zmq_msg_size(&msg);
			if (write(STDOUT_FILENO, p, pend - p) != pend - p) fatal("write");
			if (write(STDOUT_FILENO, "\n", 1) != 1) fatal("write");
			if (zmq_msg_close(&msg)) fatal("zmq_msg_close");
			if (zmq_msg_init_size(&msg, 0)) fatal("zmq_msg_init");
			if (zmq_msg_send(&msg, sock, 0) < 0) fatal("zmq_msg_send");
			if (zmq_msg_close(&msg)) fatal("zmq_msg_close");
		}
	} else {
		char *buf;
		int bufsize, bufmax;
		int val = 0;

		sock = zmq_socket(context, ZMQ_PUB);
		if (!sock) fatal("zmq_socket");
		if (zmq_bind(sock, endpoint)) fatal("zmq_bind");
		if (zmq_setsockopt(sock, ZMQ_LINGER, &val, sizeof val)) fatal("zmq_setsockopt(ZMQ_LINGER)");

		items[0].socket = NULL;
		items[0].fd = STDIN_FILENO;
		items[0].events = ZMQ_POLLIN;

		bufsize = 0;
		bufmax = 256;
		buf = malloc(bufmax);
		if (!buf) fatal("malloc");
		while (1) {
			int rc = zmq_poll(items, 1, -1);
			if (rc < 0) fatal("zmq_poll");

			if (read(STDIN_FILENO, &buf[bufsize], 1) != 1) fatal("read");
			if (buf[bufsize] == '\n') {
				zmq_msg_t msg;
				if (zmq_msg_init_size(&msg, bufsize)) fatal("zmq_msg_init_size");
				memcpy(zmq_msg_data(&msg), buf, bufsize);
				if (zmq_msg_send(&msg, sock, 0) < 0) fatal("zmq_msg_send");
				if (zmq_msg_close(&msg)) fatal("zmq_msg_close");
				bufsize = 0;
			} else if (++bufsize == bufmax) {
				bufmax <<= 1;
				buf = realloc(buf, bufmax);
				if (!buf) fatal("realloc");
			}
		}
	}
}
