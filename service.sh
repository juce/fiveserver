#!/usr/bin/env bash
fsroot=${FSROOT:-.}
export FSENV=${FSENV:-$HOME/fsenv}
export PYTHONPATH=${fsroot}/lib:$PYTHONPATH

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
    *)
        echo "Usage $0 {fiveserver|sixserver} {run|start|stop|status}"
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
        echo "Usage $0 {fiveserver|sixserver} {run|start|stop|status}"
        RETVAL=3
esac

exit $RETVAL
