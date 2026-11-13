import threading
import numpy as np
import time
import lora
import uhd
import queue
import sys
import os





class bcolors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'







np.set_printoptions(threshold=sys.maxsize)


def threshold_trigger_thread(index_queue, SF_sample_th, queue_arr_tuple):
    queue_arr = np.array(queue_arr_tuple, dtype=queue.Queue)
    samples_counter = np.zeros((SF_sample_th.size))

    while True:
        item = index_queue.get()
        samples_counter = samples_counter + 1
        for index, th in enumerate(SF_sample_th):
            if samples_counter[index] >= th:
                queue_arr[index].put(1)
                samples_counter[index] = 0


def decoder_thread(shared_buffer, complex_data_number, buf_size, sf_index_queue, pkt_queue, sf, BW, fs, SF_sample_th):
    #print("Decoder on SF", str(sf), ", Thread ID:", str(threading.get_ident()))
    sf_minimum_win_size_arr = np.array((650e3, 1.2e6, 2e6, 3.6e6, 8e6, 14.5e6), dtype= np.uint32)
    sf_minimum_win_size = int(1.1 * sf_minimum_win_size_arr[sf-7])

    buf_length = complex_data_number * buf_size
    temp_samples = np.zeros(sf_minimum_win_size, dtype=np.complex64)
    rec_buffer = shared_buffer
    sf_windows_len = complex_data_number * SF_sample_th
    old_rec = 0
    rep_count = 0

    win_start_index = 0

    count_debug = 0

    while True:

        count_debug = count_debug + 1
        if(count_debug == 5):
            #print(bcolors.OKGREEN + "thread on SF",sf, "is alive!!!" + bcolors.ENDC)
            count_debug = 0
        #sys.stdout.flush()
        # start_t = time.time()
        #print("Decoder")
        item = sf_index_queue.get()
        #print("Starting decoding on SF",sf)
        c = rec_buffer[win_start_index:win_start_index + sf_windows_len]
        win_start_index = (win_start_index + sf_windows_len) % buf_length
        # print(c.tolist())
        # c.real = np.array(samples_buffer[cursor:cursor+block_size:2 * (1 * float_size) ], dtype = np.float32)
        # c.imag = np.array(samples_buffer[cursor+(1 * float_size) :cursor+block_size:2 * (1 * float_size) ], dtype = np.float32)
        #DECODE THE SAMPLES THROUGH THE DECODE FUNCTION FROM THE LORA MODULE
        #print("Decoder End")

        #print("Passing the samples from sf", sf,  "to a decoder thread")
        threading.Thread(target=thread_decode, args=(np.concatenate((temp_samples,c)), sf, BW, fs, pkt_queue), daemon=True).start()

        temp_samples = c[-sf_minimum_win_size:]

    return
    #print("esco")

def thread_decode(samples, sf, BW, fs, pkt_queue):
    #print(bcolors.OKBLUE + "[DECODER PROCESS] Decoding samples from sf", sf, bcolors.ENDC)

    ans = lora.decode(samples, sf, BW, fs)
    if ans.size > 0:
        #print("# DECODED PACKETS", ans.size)

        for pkt in ans:
            pkt_queue.put(pkt)
    else:
        pkt_queue.put(int(0))

        # for pkt in ans:
        #     print(pkt)



def tx_burst(sample_rate, center_freq, pkt_list, sleep_time, sending, streamer, amplitude, verbose):

    #usrp = uhd.usrp.MultiUSRP("address=" + address)

    #print("TX Acquiring")
    sending.set()
    metadata = uhd.types.TXMetadata()
    for index,pkt in enumerate(pkt_list):
        print("Transmitter: Processing Packet #", index)

        buffer_samps = streamer.get_max_num_samps()

        samples = amplitude * lora.encode(center_freq, pkt.SF, pkt.BW, pkt.payload, sample_rate, pkt.src, pkt.dst, pkt.seqn, 1, 1, 0, 8)
        print("Encoded Packet #", index)
        proto_len = samples.shape[-1]
        send_samps = 0
        samples = samples.reshape(1, samples.size)
        while send_samps < proto_len:
            real_samps = min(proto_len - send_samps, buffer_samps)
            n_samples = streamer.send(samples[:, send_samps:send_samps + real_samps], metadata)
            send_samps += n_samples
            if (verbose):
                print("Sent samples", n_samples)
        metadata.end_of_burst = True
        print("Ending Burst for Packet #", index)

        streamer.send(np.zeros((1, 1), dtype=np.complex64), metadata)

        print("Sent Packet #", index)

        # Send EOB to terminate Tx

        #print("Sent packet with seq number", pkt.seqn)
        time.sleep(sleep_time)

    sending.clear()


def tx_burst_multi_sf(sample_rate, center_freq, pkt_list, sleep_time, sending, streamer, sf_list, amplitude):

    #usrp = uhd.usrp.MultiUSRP("address=" + address)


    n_pack = len(pkt_list)
    print("N_pack:", n_pack)
    #remaining_pkt = np.array([len(pkt_list)] * len(sf_list))
    pkt_count = np.zeros((len(sf_list)-1), dtype=np.uint32)
    sf_list.sort(reverse = True)
    #print("TX Acquiring")
    metadata = uhd.types.TXMetadata()
    for index,pkt in enumerate(pkt_list):

        sending.set()
        #print("TX Acquired")

        buffer_samps = streamer.get_max_num_samps()
        #print("LOL")

        samples = amplitude * lora.encode(center_freq, sf_list[0], pkt.BW, pkt.payload, sample_rate, pkt.src, pkt.dst, pkt.seqn, 1, 1, 0, 8)
        max_len = samples.size

        for i,sf in enumerate(sf_list[1:]):
            add_samples = np.zeros((samples.size), dtype=np.complex64)
            length = 0
            incr = 0
            coded_pkt = 0
            while (pkt_count[i] < n_pack):
                current_pkt = pkt_list[pkt_count[i]]
                current_samples = lora.encode(center_freq, sf, current_pkt.BW, current_pkt.payload, sample_rate, current_pkt.src, current_pkt.dst,
                                      current_pkt.seqn, 1, 1, 0, 8)

                add_samples[length:length + current_samples.size] = current_samples
                length = length + current_samples.size
                coded_pkt = coded_pkt + 1
                pkt_count[i] = pkt_count[i] + 1
                if (length * ((coded_pkt + 1) / coded_pkt)) > max_len:
                    print("Pkt Count for SF", sf,":", pkt_count[i])
                    break

            samples = samples + add_samples

        proto_len = samples.shape[-1]
        send_samps = 0
        samples = samples.reshape(1, samples.size)
        while send_samps < proto_len:

            real_samps = min(proto_len, buffer_samps - send_samps)
            if real_samps < proto_len:
                n_samples = streamer.send(samples[:real_samps], metadata)
            else:
                n_samples = streamer.send(samples, metadata)
            send_samps += n_samples

            metadata.end_of_burst = True
            streamer.send(np.zeros((1, 1), dtype=np.complex64), metadata)

        # Send EOB to terminate Tx

        #print("Sent packet with seq number", pkt.seqn)
        time.sleep(sleep_time)

    sending.clear()


def tx(sample_rate, center_freq, pkt_queue, sleep_time, sending, streamer, amplitude, verbose = False):

    #usrp = uhd.usrp.MultiUSRP("address=" + address)

    sending.set()
    metadata = uhd.types.TXMetadata()
    while sending.is_set():

        try:
            pkt = pkt_queue.get(timeout=1.0)  # Add timeout to prevent indefinite blocking
        except queue.Empty:
            continue  # Continue checking if sending is still set
            
        if(verbose):
            print("Sending pkt", pkt)

        buffer_samps = streamer.get_max_num_samps()

        samples = amplitude * lora.encode(center_freq, pkt.SF, pkt.BW, pkt.payload, sample_rate, pkt.src, pkt.dst, pkt.seqn, 1, 1, 0, 8)
        proto_len = samples.shape[-1]
        send_samps = 0
        samples = samples.reshape(1, samples.size)
        while send_samps < proto_len:

            real_samps = min(proto_len - send_samps, buffer_samps)
            n_samples = streamer.send(samples[:, send_samps:send_samps + real_samps], metadata)
            send_samps += n_samples

            if(verbose):
                print("Sent samples", n_samples)
                print("Total Sent Samples", send_samps)

        metadata.end_of_burst = True
        streamer.send(np.zeros((1, 1), dtype=np.complex64), metadata)

        # Send EOB to terminate Tx

        #print("Sent packet with seq number", pkt.seqn)
        time.sleep(sleep_time)

    sending.clear()


def rx(sample_rate, sf_list, bandwidth, receiving, packet_queue, complex_data_number, streamer, pause_rec,buf_size = 120):
    BUF_SIZE = int(buf_size) #MAKE SURE THIS NUMBER IS A MULTIPLE OF THE MAXIMUM SAMPLES THRESHOLD DIVIDED BY COMPLEX_DATA_NUMBER
    data_size = 8  # bytes
    cursor = 0
    block_size = complex_data_number * data_size
    SF_sample_th = np.array([1, 1, 1, 1, 1, 1])
    sf_arr = np.array([7, 8, 9, 10, 11, 12])


    indexes = np.isin(sf_arr, sf_list)

    SF_sample_th = SF_sample_th[indexes]
    sf_arr = sf_arr[indexes]


    queue_arr = np.empty(shape=(sf_arr.size,), dtype=queue.Queue)
    threads_arr = np.empty(shape=(sf_arr.size,), dtype=threading.Thread)

    #CREATION OF THE SHARED BUFFER (regular memory since threads share memory space)
    samples_buffer = np.zeros(complex_data_number * BUF_SIZE, dtype=np.complex64)
    buffer_size = samples_buffer.size
    index_queue = queue.Queue()

    print("########################")
    print("Using threading instead of multiprocessing")
    print("########################")
    #CREATION OF THE DECODER THREADS

    for index, sf in enumerate(sf_arr):
        queue_arr[index] = queue.Queue()
        threads_arr[index] = threading.Thread(name="Decoder SF" + str(sf), target=decoder_thread, args=(samples_buffer, complex_data_number, BUF_SIZE,
                                                                        queue_arr[index], packet_queue[index], sf, bandwidth,
                                                                        sample_rate, SF_sample_th[index]), daemon=True)

        threads_arr[index].start()
        while (not (threads_arr[index].is_alive())):
            time.sleep(0.1)

    for index, sf in enumerate(sf_arr):
        while (not (threads_arr[index].is_alive())):
            threads_arr[index] = threading.Thread(name="Decoder SF" + str(sf), target=decoder_thread,
                                              args=(samples_buffer, complex_data_number, BUF_SIZE,
                                                    queue_arr[index], packet_queue[index], sf, bandwidth,
                                                    sample_rate, SF_sample_th[index]), daemon=True)

            threads_arr[index].start()
            time.sleep(1)

    #CREATION OF THE THRESHOLD TRIGGER THREAD
    trigger_thread = threading.Thread(target=threshold_trigger_thread, args=(index_queue, SF_sample_th, tuple(queue_arr)), daemon=True)
    trigger_thread.start()


    debug = False


    # # Start Stream
    stream_cmd = uhd.types.StreamCMD(uhd.types.StreamMode.start_cont)
    stream_cmd.stream_now = True
    streamer.issue_stream_cmd(stream_cmd)
    receiving.set()

    metadata = uhd.types.RXMetadata()

    print("Starting...")

    #("Channels",streamer.get_num_channels())
    buf_length = complex_data_number
    recv_buffer = np.zeros((buf_length,), dtype=np.complex64)
    #START RECEIVING
    while receiving.is_set():
        try:

            pause_rec.wait()
            streamer.recv(recv_buffer, metadata)
            #streamer.recv(recv_buffer, metadata, timeout = 10)
            #streamer.recv(samples_buffer[cursor:cursor + complex_data_number], metadata)
            if(debug):
                print(bcolors.OKGREEN + "DEBUG metadata ", metadata, bcolors.ENDC)

            samples_buffer[cursor:cursor + buf_length] = recv_buffer
            cursor = (cursor + buf_length) % buffer_size
            if(cursor % complex_data_number == 0):
                index_queue.put(cursor)
            # cursor = (cursor + complex_data_number) % buffer_size
            #print("Rec")
            if(cursor == 0):
                # stream_cmd = uhd.types.StreamCMD(uhd.types.StreamMode.stop_cont)
                # streamer.issue_stream_cmd(stream_cmd)
                # time.sleep(0.1)
                # stream_cmd = uhd.types.StreamCMD(uhd.types.StreamMode.start_cont)
                # stream_cmd.stream_now = True
                # streamer.issue_stream_cmd(stream_cmd)
                pass




        except KeyboardInterrupt:
            print("Stopping RX")
            rec = False
            # Stop Stream
            stream_cmd = uhd.types.StreamCMD(uhd.types.StreamMode.stop_cont)
            streamer.issue_stream_cmd(stream_cmd)
            for thread in threads_arr:
                # Threads will stop automatically when receiving.value becomes False
                pass
            break

    else:
        print("Stopping RX")
        # Stop Stream
        stream_cmd = uhd.types.StreamCMD(uhd.types.StreamMode.stop_cont)
        streamer.issue_stream_cmd(stream_cmd)
        for thread in threads_arr:
            # Threads will stop automatically when receiving.value becomes False
            pass

class lora_transceiver():

    def __init__(self,serial,rx_gain,tx_gain,bandwidth, rx_freq, tx_freq, sample_rate, rx_channel_ID, tx_channel_ID, signal_amplitude = 1):
        self.serial = serial
        self.rx_gain = rx_gain # dB
        self.tx_gain = tx_gain # dB
        self.bandwidth = bandwidth  # Hz
        self.rx_freq = rx_freq # Hz
        self.tx_freq = tx_freq  # Hz
        self.sample_rate = sample_rate # Hz
        self.receiving = threading.Event()
        self.sending = threading.Event()
        self.signal_amplitude = signal_amplitude
        self.usrp = uhd.usrp.MultiUSRP("serial=" + self.serial)
        self.rx_channel = rx_channel_ID
        self.tx_channel = tx_channel_ID
        self.usrp.set_rx_rate(sample_rate, self.rx_channel)
        self.usrp.set_rx_freq(uhd.libpyuhd.types.tune_request(rx_freq), self.rx_channel)
        self.usrp.set_rx_gain(rx_gain, self.rx_channel)
        self.usrp.set_rx_bandwidth(bandwidth, self.rx_channel)
        # Set up the stream and receive buffer
        st_args = uhd.usrp.StreamArgs("fc32", "sc16")
        st_args.channels = [self.rx_channel]
        self.rx_streamer = self.usrp.get_rx_stream(st_args)
        self.rx_pause_flag = threading.Event()
        self.rx_pause_flag.set()
        #

        self.usrp.set_tx_rate(sample_rate, self.tx_channel)
        self.usrp.set_tx_freq(uhd.libpyuhd.types.tune_request(tx_freq), self.tx_channel)
        self.usrp.set_tx_gain(tx_gain, self.tx_channel)
        # Set up the stream and receive buffer
        st_args = uhd.usrp.StreamArgs("fc32", "sc16")
        st_args.channels = [self.tx_channel]
        self.tx_streamer = self.usrp.get_tx_stream(st_args)
        self.rx_thread = None

        self.tx_queue = None
        self.rx_queues = None

    def set_tx_frequency(self, freq):
        """Set the transmit frequency."""
        if self.sending.is_set():
            print("Warning: Cannot change frequency while transmitting")
            return False
        
        try:
            # Additional settling time before frequency change
            time.sleep(0.5)
            
            self.tx_freq = freq
            
            # Use a longer timeout for the tune request
            tune_req = uhd.libpyuhd.types.tune_request(freq)
            tune_result = self.usrp.set_tx_freq(tune_req, self.tx_channel)
            
            # Wait longer for hardware to settle
            time.sleep(0.5)
            
            # Verify the frequency was set correctly
            actual_freq = self.usrp.get_tx_freq(self.tx_channel)
            if abs(actual_freq - freq) > 1000:  # 1kHz tolerance
                print(f"Warning: TX frequency mismatch. Requested: {freq/1e6:.3f}MHz, Actual: {actual_freq/1e6:.3f}MHz")
            
            return True
        except Exception as e:
            print(f"Error setting TX frequency: {e}")
            # Try to reset the USRP state
            try:
                time.sleep(1.0)
                # Attempt a simple frequency set without tune request
                self.usrp.set_tx_freq(freq, self.tx_channel)
                time.sleep(0.5)
                print("TX frequency set using fallback method")
                return True
            except:
                return False

    def set_rx_frequency(self, freq):
        """Set the receive frequency."""
        if self.receiving.is_set():
            print("Warning: Cannot change frequency while receiving")
            return False
            
        try:
            # Additional settling time before frequency change
            time.sleep(0.5)
            
            self.rx_freq = freq
            
            # Use a longer timeout for the tune request
            tune_req = uhd.libpyuhd.types.tune_request(freq)
            tune_result = self.usrp.set_rx_freq(tune_req, self.rx_channel)
            
            # Wait longer for hardware to settle
            time.sleep(0.5)
            
            # Verify the frequency was set correctly
            actual_freq = self.usrp.get_rx_freq(self.rx_channel)
            if abs(actual_freq - freq) > 1000:  # 1kHz tolerance
                print(f"Warning: RX frequency mismatch. Requested: {freq/1e6:.3f}MHz, Actual: {actual_freq/1e6:.3f}MHz")
            
            return True
        except Exception as e:
            print(f"Error setting RX frequency: {e}")
            # Try to reset the USRP state
            try:
                time.sleep(1.0)
                # Attempt a simple frequency set without tune request
                self.usrp.set_rx_freq(freq, self.rx_channel)
                time.sleep(0.5)
                print("RX frequency set using fallback method")
                return True
            except:
                return False

    def rx_stop(self, wait = False):
        self.receiving.clear()
        
        # Stop the stream first
        try:
            stream_cmd = uhd.types.StreamCMD(uhd.types.StreamMode.stop_cont)
            self.rx_streamer.issue_stream_cmd(stream_cmd)
            time.sleep(0.5)  # Allow stream to stop
        except Exception as e:
            print(f"Error stopping RX stream: {e}")
        
        if wait and self.rx_thread:
            try:
                self.rx_thread.join(timeout=10.0)  # Increased timeout
                if self.rx_thread.is_alive():
                    print("Warning: RX thread did not stop gracefully")
            except Exception as e:
                print(f"Error stopping RX thread: {e}")
        self.rx_thread = None

    def tx_stop(self):
        if self.sending.is_set():
            self.sending.clear()
            # Give more time for TX operations to complete
            time.sleep(1.0)

    def cleanup(self):
        """Properly cleanup all resources"""
        try:
            print("Cleaning up USRP resources...")
            self.tx_stop()
            self.rx_stop(wait=True)
            
            # Additional cleanup time
            time.sleep(2.0)
            
            # Reset USRP to a known state
            try:
                # Stop any ongoing streams
                stream_cmd = uhd.types.StreamCMD(uhd.types.StreamMode.stop_cont)
                self.rx_streamer.issue_stream_cmd(stream_cmd)
                time.sleep(0.5)
            except:
                pass
                
        except Exception as e:
            print(f"Error during cleanup: {e}")


    def rx_start(self, sf_list, complex_data_number = 3000000, block_size = 20):
        # THE DEFAULT MINIMUM BLOCK OF SAMPLES ROUGHLY CORRESPONDS TO 5 TIMES THE SIZE OF A 251 BYTES SF7 PACKET
        rx_packet_queue = np.empty((len(sf_list)), dtype=queue.Queue)
        #print("SF LIST",sf_list)
        print("RX Start")
        for index in range(len(sf_list)):
            rx_packet_queue[index] = queue.Queue()
        self.rx_thread = threading.Thread(name = "Receiver", target=rx, args=(self.sample_rate, sf_list, self.bandwidth, self.receiving, rx_packet_queue, complex_data_number, self.rx_streamer, self.rx_pause_flag, block_size), daemon=True)
        self.rx_thread.start()
        self.rx_queues = rx_packet_queue
        return rx_packet_queue

    def rx_pause(self):
        if self.rx_pause_flag:
            self.rx_pause_flag.clear()

    def rx_resume(self):
        if self.rx_pause_flag:
            self.rx_pause_flag.set()

    def tx_send_burst(self, pkt_list, sleep_time, verbose = False):
        if(not self.sending.is_set()):
            tx_burst_thread = threading.Thread(target=tx_burst, args=(self.sample_rate, self.tx_freq, pkt_list, sleep_time, self.sending, self.tx_streamer, self.signal_amplitude, verbose), daemon=True)
            tx_burst_thread.start()
            return tx_burst_thread
        else:
            print("The radio is already transmitting!")
            return None

    def tx_send_burst_multi_sf(self, pkt_list, sleep_time, sf_list):
        if(not self.sending.is_set()):
            tx_burst_thread = threading.Thread(target=tx_burst_multi_sf, args=(self.sample_rate, self.tx_freq, pkt_list, sleep_time, self.sending, self.tx_streamer, self.signal_amplitude, sf_list), daemon=True)
            tx_burst_thread.start()
            return tx_burst_thread
        else:
            print("The radio is already transmitting!")
            return None



    def tx_start(self, sleep_time, verbose = False):

        if(not self.sending.is_set()):
            self.tx_queue = queue.Queue()
            tx_thread = threading.Thread(name="Transmitter", target=tx, args=(self.sample_rate, self.tx_freq, self.tx_queue, sleep_time, self.sending, self.tx_streamer, self.signal_amplitude, verbose))
            tx_thread.start()
            return self.tx_queue

        else:
            print("TX is already ON!")
            return self.tx_queue



        # print("Main class", self.rx_streamer)
















