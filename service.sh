#!/usr/bin/env bash
fsroot=${FSROOT:-.}
export FSENV=${FSENV:-.local}
export PYTHONPATH=${fsroot}/lib:$PYTHONPATH

# this is needed on MacOS
export LD_LIBRARY_PATH=/usr/local/mysql/lib

RETVAL=0

case "$1" in
    fiveserver)
        PROG=fiveserver
        TAC=${fsroot}/tac/fiveserver.tac
        LOG=${fsroot}/log/fiveserver.log
        PID=${fsroot}/log/fiveserver.pid
        ;;
    sixserver)
        PROG=sixserver
        TAC=${fsroot}/tac/sixserver.tac
        LOG=${fsroot}/log/sixserver.log
        PID=${fsroot}/log/sixserver.pid
        ;;
    we10le)
        PROG=we10le
        TAC=${fsroot}/tac/we10le.tac
        LOG=${fsroot}/log/we10le.log
        PID=${fsroot}/log/we10le.pid
        ;;
    *)
        echo "Usage $0 {fiveserver|sixserver|we10le} {run|start|stop|status}"
        RETVAL=3
        exit $RETVAL
esac

case "$2" in
    run)
        ${FSENV}/bin/twistd -noy $TAC
        ;;
    runexec)
        exec ${FSENV}/bin/twistd -noy $TAC --logfile $LOG --pidfile $PID
        ;;
    start)
        ${FSENV}/bin/twistd -y $TAC --logfile $LOG --pidfile $PID
        ;;
    stop)
        cat $PID | xargs kill
        ;;
    status)
        if [ -f $PID ]; then
            pid=`cat $PID`
            ps $pid >/dev/null 2>&1
            if [ $? = 0 ]; then
                echo "$PROG ($pid) is running ..."
            else
                echo "$PROG is not running but pid-file exists"
                RETVAL=1
            fi
        else
            echo "$PROG is stopped"
        fi
        ;;
    *)
        echo "Usage $0 {fiveserver|sixserver|we10le} {run|start|stop|status}"
        RETVAL=3
esac

exit $RETVAL
