# Copyright (c) 2018, Autonomous Networks Research Group. All rights reserved.
#     Contributor: Rahul Radhakrishnan
#     Read license file in main directory for more details  

import socket
import json
import sys
import logging
import Crypto.Hash.MD5 as MD5
import Crypto.PublicKey.RSA as RSA
import ast
import pprint
import iota
import base64
from Crypto.Cipher import AES

# Establish Connection
server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
IP_address = str(sys.argv[1])
Port = int(sys.argv[2])
server.connect((IP_address, Port))

# Connect to the tangle
seed = ""
client = "http://node02.iotatoken.nl:14265"
iota_api = iota.Iota(client, seed)

# Generate keys
encrypt_key = RSA.generate(2048)
signature_key = RSA.generate(2048, e=65537)

# Set values
invoice_address = iota_api.get_new_addresses(count=1)
invoice_address = str(invoice_address['addresses'][0].address)
bs = 32

# Info to be received from Seller
payment_address = ""
payment_granularity = 0
secret_key = ""
quantity = 0
cost = 0
data_type = ""
signature_required = 0
seller_public_key = ""

# Tangle logs
#logger = create_logger(severity=logging.DEBUG)
#iota_api.adapter.set_logger(logger)



def validate_user_input(input_str, available_data):
    input_str = input_str.split(" ")
    if input_str[0] not in available_data.keys():
        return False
    return True


def create_logger(severity):
    logging.basicConfig(
        level=severity,
        format="[%(asctime)s] %(levelname)s %(module)s:%(funcName)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    return logging.getLogger(__name__)

def _unpad(s):
    return s[:-ord(s[len(s)-1:])]

def decrypt(enc):
    """
    AES based decryption(using Session Key)
    :param enc: Encrypted text to be decrypted
    :return: Original Message<String>
    """
    enc = base64.b64decode(enc)
    iv = enc[:AES.block_size]
    cipher = AES.new(secret_key, AES.MODE_CBC, iv)
    return _unpad(cipher.decrypt(enc[AES.block_size:])).decode('utf-8')

def prepareJSONstring(message_type, data, signature=None, verification=None):
    """
    Prepares the JSON message format to be sent to the Seller
    :param message_type: ORDER/DATA_ACK/PAYMENT_ACK/EXIT
    :param data: Corresponding data
    :param signature: Signed Data
    :param verification: Address or the transaction ID in Tangle/Blockchain
    :return: JSON dictionary
    """

    json_data = {}

    json_data['message_type'] = message_type
    json_data['data'] = data

    if signature:
        json_data['signature'] = signature
    else:
        json_data['signature'] = ""
    if verification:
        json_data['verification'] = verification
    else:
        json_data['verification'] = ""

    return json.dumps(json_data)


def signData(plaintext):
    """
    Signs the Data
    :param plaintext: String to be signed
    :return: signature<Tuple>
    """
    hash = MD5.new(plaintext).digest()
    signature = signature_key.sign(hash, '')
    return signature


def verifySignature(message, signature):
    """
    Verifies the Signature
    :param message: String to be verified
    :param signature: Signature provided by the Seller
    :return: True/False
    """
    hash = MD5.new(message).digest()
    return seller_public_key.verify(hash, signature)


def sendTransaction(transaction):
    try:
        bundle = iota_api.send_transfer(depth=2, transfers=[transaction])
        url = "https://thetangle.org/bundle/" + str(bundle["bundle"].hash)
        print url
        #.info(url)
        return str(iota_api.find_transactions([bundle["bundle"].hash])['hashes'][0])
    except iota.adapter.BadApiResponse as error:
        #logger.error(error)
        return False

def prepareTransaction(message=None, value=0):
    """
    Prepares the transaction to be made through the distributed ledger
    :param message: Message for the payment
    :param value: Amount of cryptocurrencies to be sent
    :return: Transaction ID/ Address/ Transaction hash
    """
    if message:
        message = iota.TryteString.from_string(message)
    tag = iota.Tag(b"SDPPBUYER")

    transaction = iota.ProposedTransaction(
        address=payment_address,
        value=value,
        message=message,
        tag=tag
    )

    return sendTransaction(transaction)

def dataTransfer():
    """
    Actual Data Transfer happens here
    :return: Remaining money to be paid
    """
    counter = 1
    filename = data_type + ".txt"
    f = open(filename, "a")
    remaining = quantity

    print "-------Receiving Data Starts-------"
    while counter <= quantity:
        message = server.recv(2048)
        message = json.loads(message)

        # print "Data " + str(counter) + " received"
        # print pprint.pprint(message)

        access_data = json.loads(decrypt(message['data']))
        sensor_data = access_data['data']
        message_type = message['message_type']

        # verify signature
        seller_signature = message['signature']
        if verifySignature(message['data'], seller_signature) is not True:
            print "Invalid Signature, exiting.."
            exit()

        f.write(sensor_data + '\n')

        # Setting the values to send
        send_message_type = "DATA_ACK"
        transaction_hash = None
        send_data = "1"
        send_signature = None

        if signature_required == 1:
            send_signature = signData(send_data)

        # Send cryptocurrencies
        if message_type == "DATA_INVOICE":
            remaining = remaining - payment_granularity
            #TODO verify if the seller's invoice is present in the tangle/blockchain
            verify_addr = message['verification']

            value = 0
            # value = access_data['invoice']
            print "Payment made: ",
            transaction_hash = prepareTransaction(value=value)
            send_message_type = "PAYMENT_ACK"

        json_string = prepareJSONstring(send_message_type, send_data, send_signature, transaction_hash)
        server.send(json_string)

        # print "Ack " + str(counter) + " sent"
        # print pprint.pprint(json.loads(json_string))

        counter = counter + 1
    print "-------Receiving Data Ends--------"
    return remaining

def prepareOrderData(data_type, quantity, currency):
    data = {}

    data['data_type'] = data_type
    data['quantity'] = quantity
    data['currency'] = currency

    data['signature-key'] = signature_key.publickey().exportKey('OpenSSH')
    data['encryption-key'] = encrypt_key.publickey().exportKey('OpenSSH')

    data['address'] = invoice_address

    return data

def placeOrder(available_data):
    """
    Processes the order from the Buyer and also records the order in the ledger
    :param available_data: Menu provided by the Seller
    :return: None
    """
    global secret_key, quantity, cost, data_type

    print "\nPlease enter the type of data, quantity and currency you wish to pay"
    print "Data type: ",
    data_type = sys.stdin.readline()
    data_type = data_type.strip()

    # TODO validate user input
    '''
    while not validate_user_input(data_type, available_data):
        print "Please follow this format : <data_request> <quantity>\n"
        data_type = sys.stdin.readline()
    '''
    cost = int(available_data[data_type])

    print "Quantity: ",
    quantity = sys.stdin.readline()
    quantity = int(quantity)

    print "Currency: ",
    currency = sys.stdin.readline()

    buyer_order = str(data_type)+ ' ' + str(quantity)

    # Sign the order
    signature = signData(buyer_order)

    # Record the transaction in tangle/blockchain
    print "Order recorded in the distributed ledger: ",
    transaction_hash = prepareTransaction(message=buyer_order + ' ' + str(signature))

    data = prepareOrderData(data_type, quantity, currency)

    json_string = prepareJSONstring("ORDER", json.dumps(data), signature, transaction_hash)

    server.send(json_string)

    # Receive Session Key
    message = server.recv(2048)
    message = json.loads(message)
    secret_key = encrypt_key.decrypt(ast.literal_eval(message['data']))

def receiveMenu():
    """
    Receive the Menu and other details from the Seller
    :return: Returns the Menu
    """
    global payment_address, payment_granularity, signature_required, seller_public_key

    message = server.recv(2048)
    message = json.loads(message)
    data = json.loads(str(message['data']))

    pprint.pprint(data)

    payment_granularity = int(data['payment-granularity'])
    payment_address = iota.Address(str(data['payment-address']))
    signature_required = int(data['signature-required'])
    seller_public_key = RSA.importKey(data['public-key'])

    if verifySignature(message['data'], message['signature']) is not True:
        print "Invalid Signature, exiting.."
        exit()

    return data['menu']


if len(sys.argv) != 3:
    print "Correct usage: script, IP address, port number"
    exit()

while True:

    available_data = receiveMenu()

    placeOrder(available_data)

    remaining = dataTransfer()

    data = "close"
    signature = None
    transaction_hash = None
    if signature_required == 1:
        signature = signData(data)

    if remaining > 0:
        # value = remaining * cost
        value = 0
        print "Payment made for the remaining data: ",
        transaction_hash = prepareTransaction(value=value)

    json_string = prepareJSONstring("EXIT", data, signature, transaction_hash)
    server.send(json_string)
    print "Done!"
    break

server.close()
