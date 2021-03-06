import sys
import os

sys.path.append(os.path.split(os.getcwd())[0])
sys.path.append(os.getcwd())

from AVCommon.protocol import Protocol
from AVCommon.procedure import Procedure
from AVCommon.mq import MQStar

from AVCommon.logger import logging
from AVCommon import command

def server_procedure(mq, clients, procedure):
    global received
    exit = False
    logging.debug("- SERVER PROCEDURE, len: %s" % len(procedure))
    numcommands = len(procedure)

    p = {}
    for c in clients:
        p[c] = Protocol(mq, c, procedure)
        p[c].send_next_command()

    ended = 0
    answered = 0
    while not exit and ended < len(clients):
        rec = mq.receive_server(blocking=True, timeout=10)
        if rec is not None:
            logging.debug("- SERVER RECEIVED %s %s" % (rec, type(rec)))
            c, msg = rec
            answer = p[c].receive_answer(c, msg)
            answered += 1
            logging.debug("- SERVER RECEIVED ANSWER: %s" % answer.success)
            if answer.name == "END" or answer.success == False:
                ended += 1
                logging.debug("- SERVER RECEIVE END")
            if answer.success:
                p[c].send_next_command()

        else:
            logging.debug("- SERVER RECEIVED empty")
            exit = True

    logging.debug("answered: %s, ended: %s, numcommands: %s" % (answered, ended, numcommands))
    assert (ended == len(clients))
    assert (answered == (len(clients) * numcommands))

def test_ProtocolEval():
    host = "localhost"
    mq = MQStar(host)
    mq.clean()
    c = "client1"
    mq.add_client(c)

    commands = ["BEGIN", ("EVAL_SERVER", None, "dir()"),
                ("EVAL_SERVER", None, "locals()"),
                ("EVAL_SERVER", None, "__import__('os').getcwd()"),
                ("END", None, None)]
    procedure = Procedure("PROC", commands)

    class D:
        pass
    d = D()
    d.mq = mq
    p = Protocol(d, c, procedure)

    while p.send_next_command():
        logging.debug("sent command: %s" % p.last_command)

    print("---- START RECEIVING ----")
    exit = False
    while not exit:
        rec = mq.receive_server(blocking=True, timeout=10)

        if rec is not None:
            logging.debug("- SERVER RECEIVED %s %s" % (rec, type(rec)))
            c, msg = rec
            command_unserialize = command.unserialize(msg)

            answer = p.receive_answer(c, command_unserialize)
            logging.debug("- SERVER RECEIVED ANSWER: %s" % answer.success)
            if answer.name == "END" or not answer.success:
                logging.debug("- SERVER RECEIVE END")
                #if answer.success:
            a = """('client1', ('EVAL_SERVER', True, {'self': <Command_EVAL_SERVER.Command_EVAL_SERVER object at 0x10931f810>, 'args': 'locals()'}))"""#   p.send_next_command()

        else:
            logging.debug("- SERVER RECEIVED empty")
            exit = True
    print("---- STOP RECEIVING ----")

def test_ProtocolCall():
    host = "localhost"
    mq = MQStar(host)
    mq.clean()
    c = "client1"
    mq.add_client(c)

    yaml = """

HELLO:
    - EVAL_SERVER: 3+2

BASIC:
    - EVAL_SERVER: dir()
    - CALL: HELLO

CALLER:
    - BEGIN
    - CALL: BASIC
    - EVAL_SERVER: locals()
    - END
"""
    procedures = Procedure.load_from_yaml(yaml)

    caller = Procedure.procedures["CALLER"]
    basic = Procedure.procedures["BASIC"]

    class D:
        pass
    d = D()
    d.mq = mq

    p = Protocol(d, c, caller)
    while p.send_next_command():
        logging.debug("sent command")

    exit = False
    answers =0
    while not exit:
        rec = mq.receive_server(blocking=True, timeout=10)
        if rec is not None:
            logging.debug("- SERVER RECEIVED %s %s" % (rec, type(rec)))
            c, msg = rec
            command_unserialize = command.unserialize(msg)
            answer = p.receive_answer(c, command_unserialize)
            logging.debug("- SERVER RECEIVED ANSWER: %s" % answer.success)
            if answer.success:
                answers += 1
            if answer.name == "END" or not answer.success:
                logging.debug("- SERVER RECEIVE END")
                #if answer.success:
                exit = True

        else:
            logging.debug("- SERVER RECEIVED empty")
            exit = True

    assert answers == 7, "wrong answers: %s" % answers

if __name__ == '__main__':

    #test_ProtocolEval()
    test_ProtocolCall()
