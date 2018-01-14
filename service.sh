#!/bin/sh
export FSENV=$HOME/fsenv
export PYTHONPATH=./lib:$PYTHONPATH

RETVAL=0

case "$1" in
    fiveserver)
        PROG=fiveserver
        TAC=./etc/fiveserver.tac
        LOG=./log/fiveserver.log
        PID=./fiveserver.pid
        ;;
    sixserver)
        PROG=sixserver
        TAC=./etc/sixserver.tac
        LOG=./log/sixserver.log
        PID=./sixserver.pid
        ;;
    *)
        echo "Usage $0 {fiveserver|sixserver} {run|start|stop|status}"
        RETVAL=3
        exit $RETVAL
esac

case "$2" in
    run)
        ${FSENV}/bin/twistd -noy $TAC
        ;;
    start)
        ${FSENV}/bin/twistd -ny $TAC --logfile $LOG --pidfile $PID &
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
        echo "Usage $0 {fiveserver|sixserver} {run|start|stop|status}"
        RETVAL=3
esac

exit $RETVAL
