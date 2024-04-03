import asyncio
import requests
import sys
import websockets
import subprocess
import os
import json
import string
import random
import pathlib
from websockets.legacy.client import WebSocketClientProtocol
from base64 import b64encode, b64decode
from threading import Thread
from flask import Flask, Response, Request, request, send_from_directory, redirect, jsonify
from typing import Dict, Callable, Awaitable, Union, Optional, List

PRESERVE_TEMP_ARG = "--preserve-temp"
DOWNLOAD_THREADS_ARG = "--download-threads"
DOWNLOAD_THREADS_SHORT_ARG = "-t"

DOWNLOAD_THREADS_DEFAULT = 10
HOST_ADDRESS = "0.0.0.0"
WEB_SERVER_PORT = 5000
WEBSOCKET_PORT = 6950

CHUNK_FAILS = 0


def check_for_arguments(arguments: Union[str, List[str]]) -> bool:
    if type(arguments) != list:
        arguments = [arguments]
    
    for argument in arguments:
        if argument in sys.argv:
            return True
        
def get_argument_value(arguments: Union[str, List[str]]) -> str:
    for argument in arguments:
        try:
            return sys.argv[sys.argv.index(argument) + 1]
        except:
            pass

    return None

index_file_name = "index.m3u8"

class Color:
    BLACK = 0
    RED = 1
    GREEN = 2
    YELLOW = 3
    BLUE = 4
    MAGENTA = 5
    CYAN = 6
    WHITE = 7
    RESET = "\033[0m"

    FORE_GEN = lambda fore: "\033[" + "3" + str(fore) + "m"
    BACK_GEN = lambda back: "\033[" + "4" + str(back) + "m"
    FORE_RGB = lambda r, g, b: "\033[38;2;" + str(r) + ";" + str(g) + ";" + str(b) + "m"
    DECORATION = lambda dec: "\033[" + str(dec) + "m"

class Queue:
    def __init__(self) -> None:
        self.queue = []

    def add(self, url: str) -> None:
        self.queue.append(url)

    def remove(self, url: str) -> None:
        self.queue.remove(url)

    def list(self) -> list:
        return self.queue

class WebServer:
    def __init__(self, host: str, port: int, queue: Queue, endpoints: Optional[Dict[str, Union[Callable, Awaitable]]] = None) -> None:
        self.host = host
        self.port = port
        self.endpoints = endpoints or {}
        self.queue = queue

    def run(self) -> None:
        def inner() -> None:
            app = Flask(__name__)
            app.add_url_rule("/<path:path>", "handler", self.handler)
            app.add_url_rule("/", "handler", self.handler, defaults={"path": ""})
            app.run(host=self.host, port=self.port)

        t = Thread(target=inner)
        t.start()
        t.join()

    async def handler(self, path: str, *args, **kwargs) -> Response:
        def get_endpoint(path: str) -> Optional[Union[Callable, Awaitable]]:
            if path.startswith("/"):
                path = path[1:]

            if path.endswith("/"):
                path = path[:-1]

            for p in [path, f"/{path}", f"{path}/", f"/{path}/"]:
                if p in self.endpoints:
                    return self.endpoints[p]
            
            return None
        
        handler = get_endpoint(path)
        if handler is None:
            return Response(status=404)
        else:
            return await handler(request, self.queue, *args, **kwargs)

class WebSocket:
    def __init__(self, host: str, port: int, queue: Queue, handler: Awaitable) -> None:
        self.host = host
        self.port = port
        self.queue = queue
        self.handler = handler

    def run(self) -> None:
        def inner() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(websockets.serve(self.handler_wrapper, self.host, self.port))
            try:
                loop.run_forever()
            except KeyboardInterrupt:
                pass

        t = Thread(target=inner)
        t.start()

    async def handler_wrapper(self, websocket: WebSocketClientProtocol) -> None:
        await self.handler(websocket, self.queue)

class Downloader:
    def __init__(self, queue: Queue, download_threads: int, preserve_temp: bool = False, *, output_dir: str = "output") -> None:
        self.queue = queue
        self.download_threads = download_threads
        self.running = True
        self.threads = []
        self.temporary = {}
        self.preserve_temp = preserve_temp
        self.output_dir = output_dir

    def fix_video_using_ffmpeg(self, old_file, new_file):
        def inner():

            result = subprocess.Popen(['ffmpeg', '-err_detect', 'ignore_err', '-i', old_file, '-c', 'copy', new_file])
            result.wait()

            if self.preserve_temp:
                os.rename(old_file, new_file + ".tmp")
                return
            
            os.remove(old_file)                

        t = Thread(target=inner)
        t.start()

    def download_worker(self):
        async def inner():
            while len(self.temporary['retry']) != 0 or len(self.temporary['segments']) != 0:
                if not self.running:
                    await asyncio.sleep(1)
                    continue

                base_url, retry, segment_index = self.temporary['base_url'], self.temporary['retry'], self.temporary['downloaded']
                if len(retry) != 0:
                    segment_index, segment = retry.pop(0)
                    segment, segment_type = segment
                else:
                    segment, segment_type = self.temporary['segments'].pop(0)
                    self.temporary['downloaded'] += 1

                try:
                    segment = requests.get(base_url + segment if segment_type != 'url' else segment, timeout=10).content
                    self.temporary['unsaved_segments'][segment_index] = segment
                    if type(self.temporary['chunks']) == bool:
                        self.temporary['chunks'] = len(segment)
                    else:
                        self.temporary['chunks'] += len(segment)
                except:
                    global CHUNK_FAILS
                    print(f"Chunk download failed! Chunk index: {str(segment_index)}; Fail no: {CHUNK_FAILS + 1}")
                    CHUNK_FAILS += 1
                    self.temporary['retry'].append((segment_index, (segment, segment_type)))
                    continue

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(inner())
        loop.run_forever()

    def download_header(self) -> None:
        def filter_segments(index_text: str) -> List[str]:
            segments = []
            for line in index_text.splitlines():
                if line.startswith('#'):
                    continue
                if line.startswith('http'):
                    segments.append((line, 'url'))
                    continue

                segments.append((line, 'path'))
            return segments
        
        headers = {
            'Accept': '*/*',
            'Accept-Encoding': 'gzip, deflate, br',
            'Accept-Language': 'en-US,en;q=0.9',
            'Connection': 'keep-alive',
            'Host': 'r.pollllop.com',
            'Origin': 'https://rabbitstream.net',
            'Referer': 'https://rabbitstream.net/',
            'sec-ch-ua': '"Not(A:Brand";v="24", "Chromium";v="122"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Linux"',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'cross-site',
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
        }

        index = requests.get(self.temporary['base_url'] + index_file_name, headers=headers).content.decode("utf-8")

        if check_for_arguments(PRESERVE_TEMP_ARG):
            open(self.output_dir + "/temp/" + "index.m3u8", "w").write(index)
        
        self.temporary['segments'] = filter_segments(index)
        self.temporary['total'] = len(self.temporary['segments'])

    def queue_downloader(self) -> None:
        def pick_not_finished():
            for index, item in enumerate(self.queue.list()):
                if item[2] != item[3] or item[3] == 0:
                    return index, item
            
            return None, None
        
        async def inner():
            index, nf = pick_not_finished()
            while True:
                if not nf:
                    index, nf = pick_not_finished()
                    await asyncio.sleep(1)
                    continue
                
                if self.temporary.get('total') == None or self.temporary.get('last_saved_segment') + 1 == self.temporary.get('total'):
                    if self.temporary != {}:
                        self.queue.queue[index] = (self.queue.queue[index][0], self.queue.queue[index][1], self.temporary['downloaded'], self.queue.queue[index][3], self.temporary['chunks'])
                        await asyncio.sleep(.5)
                        Thread(target=self.fix_video_using_ffmpeg, args=(self.temporary['temp_file'], self.temporary['output'])).start()
                        self.temporary = {}
                        index, nf = pick_not_finished()
                        continue
                    
                    self.threads = []
                    url, output, _, _, _ = nf

                    if not pathlib.Path(self.output_dir + "/" + output).parent.exists():
                        os.makedirs(pathlib.Path(self.output_dir + "/" + output).parent)

                    self.temporary = {
                        "base_url": url,
                        "output": self.output_dir + "/" + output,
                        "downloaded": 0,
                        "total": 0,
                        "chunks": True,
                        "retry": [],
                        "segments": [],
                        "unsaved_segments": {},
                        "last_saved_segment": -1,
                        "temp_file": self.output_dir + "/" + "temp/" + "".join([random.choice(string.ascii_letters) for _ in range(16)]) + ".mp4"
                    }

                    self.download_header()
                    self.queue.queue[index] = (self.queue.queue[index][0], self.queue.queue[index][1], self.queue.queue[index][2], self.temporary['total'], self.queue.queue[index][4])
                    while len(self.threads) < self.download_threads:
                        self.threads.append(Thread(target=self.download_worker))
                        self.threads[-1].start()
                    
                    continue

                self.queue.queue[index] = (self.queue.queue[index][0], self.queue.queue[index][1], self.temporary['downloaded'], self.queue.queue[index][3], self.temporary['chunks'])

                await asyncio.sleep(1)
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(inner())
        try:
            loop.run_forever()
        except KeyboardInterrupt:
            pass

    def saver(self) -> None:
        async def inner():
            while True:
                if len(self.temporary.get('unsaved_segments', [])) == 0:
                    await asyncio.sleep(1/5)
                    continue

                try:
                    with open(self.temporary['temp_file'], "ab") as f:
                        for segment_index in sorted([*list(self.temporary['unsaved_segments'].keys())]):
                            if segment_index == self.temporary['last_saved_segment'] + 1:
                                f.write(self.temporary['unsaved_segments'][segment_index])
                                self.temporary['last_saved_segment'] += 1
                                del self.temporary['unsaved_segments'][segment_index]
                            else:
                                break
                except:
                    continue

                await asyncio.sleep(1/5)
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(inner())
        try:
            loop.run_forever()
        except KeyboardInterrupt:
            pass

    def run(self) -> None:
        Thread(target=self.saver).start()
        Thread(target=self.queue_downloader).start()

async def redirect_to_panel(request: Request, *args) -> Response:
    return redirect("/panel")

async def panel(request: Request, queue: Queue) -> Response:
    return send_from_directory("server", "panel.html")

def queue_updater(websocket: WebSocketClientProtocol, queue: Queue) -> Response:
    async def inner() -> None:
        while True:
            await websocket.send(json.dumps({'action': 'list', 'data': queue.list()}))
            await asyncio.sleep(1)
    
    asyncio.get_event_loop().create_task(inner())

async def handle_socket(websocket: WebSocketClientProtocol, queue: Queue):
    while True:
        try:
            recv = await websocket.recv()
        except websockets.exceptions.ConnectionClosedOK:
            break

        recv: dict = json.loads(recv)

        if recv.get('action') == "run_updater":
            queue_updater(websocket, queue)

        elif recv.get('action') == "add":
            def list_names_in_queue() -> List[str]:
                names = []
                for entry in queue.list():
                    names.append(entry[1])
                return names

            if 'data' not in recv or 'url' not in recv['data']:
                await websocket.send(json.dumps({"action": "add", "state": "fail",  "message": "Invalid request"}))
                continue

            for entry in queue.list():
                if entry[0] == recv['data']['url']:
                    await websocket.send(json.dumps({"action": "add", "state": "fail", "message": "URL already in queue"}))
                    continue
            
            url = recv['data']['url']
            output = recv['data'].get('output', 'output')
            if output == None or output == "":
                output = "output.mp4"

            output = f"{output}"

            index = 1
            if os.path.exists(output):
                if "." in output:
                    while os.path.exists(output.replace(".", f"{index}.")) or output.replace(".", f"{index}.") in list_names_in_queue():
                        index += 1
                    output = output.replace(".", f"{index}.")
                else:
                    while os.path.exists(output + f"{index}") or output + f"{index}" in list_names_in_queue():
                        index += 1
                    output += f"{index}"

            print("Adding URL to queue: " + url + " with output: " + output)

            queue.add((url, output, 0, 0, True))
            await websocket.send(json.dumps({"action": "add", "state": "success", "message": "URL added"}))

        elif recv.get('action') == "remove":
            if 'data' not in recv or 'url' not in recv['data']:
                await websocket.send(json.dumps({"action": "remove", "state": "fail", "message": "Invalid request"}))
                continue

            url = recv['data']['url']
            for entry in queue.list():
                if entry[0] == url:
                    queue.remove(entry)
                    await websocket.send(json.dumps({"action": "remove", "state": "success", "message": "URL removed"}))
                    break
            else:
                await websocket.send(json.dumps({"action": "remove", "state": "fail", "message": "URL not in queue"}))
                continue

        elif recv.get('action') == "list":
            await websocket.send(json.dumps({"action": "list", "state": "success", "data": queue.list()}))
            
            

def main():
    if check_for_arguments(PRESERVE_TEMP_ARG):
        print(f"{Color.FORE_GEN(Color.YELLOW)}Preserving temporary files enabled!{Color.RESET}")

    if get_argument_value([DOWNLOAD_THREADS_ARG, DOWNLOAD_THREADS_SHORT_ARG]):
        print(f"{Color.FORE_GEN(Color.YELLOW)}Download threads set to {get_argument_value([DOWNLOAD_THREADS_ARG, DOWNLOAD_THREADS_SHORT_ARG])}!{Color.RESET}")

    output_dir = get_argument_value(["--output-dir", "-od"])
    if not output_dir:
        output_dir = "output"

    else:
        print(f"{Color.FORE_GEN(Color.YELLOW)}Output directory set to {output_dir}!{Color.RESET}")

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    if not os.path.exists(output_dir + "/temp"):
        os.makedirs(output_dir + "/temp")

    for file in os.listdir(output_dir + "/temp"):
        os.remove(os.path.join(output_dir + "/temp", file))

    download_threads = get_argument_value([DOWNLOAD_THREADS_ARG, DOWNLOAD_THREADS_SHORT_ARG]) or DOWNLOAD_THREADS_DEFAULT

    queue = Queue()
    server = WebServer(HOST_ADDRESS, WEB_SERVER_PORT, queue, {'/': redirect_to_panel,
        '/panel': panel
    })
    wss = WebSocket(HOST_ADDRESS, WEBSOCKET_PORT, queue, handle_socket)
    downloader = Downloader(queue, int(download_threads), check_for_arguments(PRESERVE_TEMP_ARG), output_dir=output_dir)
    downloader.run()
    wss.run()
    server.run()

if __name__ == "__main__":
    main()
