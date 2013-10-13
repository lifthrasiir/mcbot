mcbot
=====

**mcbot** connects an IRC channel and a Minecraft server and provides the following useful features:

 - Bidirectional mediation of chat messages from/to IRC and Minecraft
 - Hangul input methods using `--`, `---` marks in the chat messages (translates English key strokes into Korean keyboard key strokes)
 - Mapping of IRC nicks and Minecraft users
 - Per-user database to track their profiles and statuses (e.g., whether the user already got the start-up item kit)
 - External scripts can issue server commands by named fifo pipes.

How to run (for Ubuntu/Upstart)
-------------------------------

1. Install the followings:
 - Python 3.3 or higher (Note: Ubuntu 13.04 already ships Python 3.3) for py3k branch
 - Python 2.7 or higher for master branch
 - libzmq-dev
 - pyzmq (use `easy_install`; `pip` does not work currently)
1. Compile 0proxy.c by `$ gcc 0proxy.c -o 0proxy` and it at the path `{ZMQ}`.
1. Copy `mcbot_defconfig.py` to `mcbot_config.py` and modify it as you want. (e.g., login welcome messages and RSS tracker)
1. Create the following upstart configurations, with modification specific to your environments applied.  The configurations may be either session jobs (upstart 1.7 or higher required) or system jobs.  Please refer the Upstart Cookbook to see [what a session job](http://upstart.ubuntu.com/cookbook/#session-job) is and [how to configure session jobs on a non-GUI environment](http://upstart.ubuntu.com/cookbook/#non-graphical-sessions-ubuntu-specific).

**~/.init/minecraft.conf**
```bash
description "Minecraft Daemon"

start on (local-filesystems and net-device-up IFACE!=lo)
stop on runlevel [!2345]

# modify paths according to your environment
chdir /home/{USERDIR}/minecraft
env MCPATH=/home/{USERDIR}/minecraft
env ZMQ=/home/{USERDIR}/minecraft/bin/0proxy
console log

pre-start script
    rm -f stdin.fifo
    rm -f stdout.fifo
    mkfifo stdin.fifo
    mkfifo stdout.fifo
    chmod 600 *.fifo

    $ZMQ -i ipc://$MCPATH/mc_server.stdin.sock > stdin.fifo &
    stdin_0proxy_pid=$!
    echo $stdin_0proxy_pid > 0proxy.stdin.pid
    $ZMQ -o ipc://$MCPATH/mc_server.stdout.sock < stdout.fifo &
    stdout_0proxy_pid=$!
    echo $stdout_0proxy_pid > 0proxy.stdout.pid
    sleep 1
end script

script
    exec 2>stdout.fifo
    exec >stdout.fifo
    # modify JVM arguments to fit your environment
    exec java -Xms1024M -Xmx1536M -XX:+UseConcMarkSweepGC -XX:+CMSIncrementalPacing -XX:ParallelGCThreads=2 -XX:+AggressiveOpts -Djava.net.preferIPv4Stack=true -Dfile.encoding=1208 -jar minecraft_server.jar nogui < stdin.fifo
end script

pre-stop script
    echo 'save-all' > stdin.fifo
    # You may need to increase the sleeping time if you run a huge Minecraft server.
    sleep 1
end script

post-stop script
    {
        stdin_0proxy_pid=`cat 0proxy.stdin.pid`
        stdout_0proxy_pid=`cat 0proxy.stdout.pid`
        kill $stdin_0proxy_pid
        kill $stdout_0proxy_pid
    } &
    sleep 2
    rm -f *.pid
    rm -f *.fifo
end script
```

**~/.init/mcbot.conf**
```bash
description "Minecraft Chatting Bot Daemon"

# The bot will automatically start/stop when the Minecraft server starts/stops.
start on started minecraft
stop on stopping minecraft

chdir /home/{USERDIR}/minecraft/bin/mcbot
console log

pre-start script
    sleep 1
end script

# Use "python" instead of "python3" if you use the master branch
exec python3 bot.py {IRCSERVER-HOSTNAME} {IRCSERVER-PORT} {IRCNICK} "#{IRCCHANNEL}" ipc\:///home/{USERDIR}/minecraft/mc_server.stdout.sock ipc\:///home/{USERDIR}/minecraft/mc_server.stdin.sock /home/{USERDIR}/minecraft/{WORLDNAME}
```

You may add external scripts (e.g., overviewer updates registered as a cron job) like:

```bash
#! /bin/sh
MCPATH=/home/{USERID}/minecraft

echo 'say §a지도 갱신을 시작합니다.§r' > $MCPATH/stdin.fifo
echo 'save-off' > $MCPATH/stdin.fifo
echo 'save-all' > $MCPATH/stdin.fifo
# Modify the following line according to your environment
/usr/local/bin/overviewer.py -p 2 --config=$MCPATH/overview/config.py $@
sed -i "s/Minecraft Overviewer/Minecraft Overviewer (updated at `date '+%Y-%m-%d %H:%M:%S'`)/" $MCPATH/overview/index.html
echo 'save-on' > $MCPATH/stdin.fifo
echo 'say §a지도 갱신이 완료되었습니다.§r' > $MCPATH/stdin.fifo
```
