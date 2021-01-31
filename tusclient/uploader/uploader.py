from typing import Optional
import time
import asyncio
from urllib.parse import urljoin

import requests
import aiohttp

from tusclient.uploader.baseuploader import BaseUploader, BaseStreamUploader

from tusclient.exceptions import TusUploadFailed, TusCommunicationError
from tusclient.request import TusRequest, AsyncTusRequest, catch_requests_error, TusStreamRequest

from tqdm import tqdm


def _verify_upload(request: TusRequest):
    if request.status_code == 204:
        return True
    else:
        raise TusUploadFailed('', request.status_code,
                              request.response_content)


class StreamUploader(BaseStreamUploader):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.chunk = None


    def upload_chunk(self):
        """
        Upload chunk of file.
        """
        self._retried = 0
        if not self.url:
            self.set_url(self.create_url())
            self.offset = 0
        self._do_request()
        self.offset = int(self.request.response_headers.get('upload-offset'))

    def set_current_chunk(self, chunk: bytes):
        self.chunk = chunk


    @catch_requests_error
    def create_url(self):
        """
        Return upload url.

        Makes request to tus server to create a new upload url for the required file upload.
        """
        resp = requests.post(
            self.client.url, headers=self.get_url_creation_headers())
        url = resp.headers.get("location")
        if url is None:
            msg = 'Attempt to retrieve create file url with status {}'.format(
                resp.status_code)
            raise TusCommunicationError(msg, resp.status_code, resp.content)
        return urljoin(self.client.url, url)

    def _do_request(self):
        self.request = TusStreamRequest(self)
        try:
            self.request.perform(self.chunk)
            _verify_upload(self.request)
        except TusUploadFailed as error:
            self._retry_or_cry(error)

    def _retry_or_cry(self, error):
        if self.retries > self._retried:
            time.sleep(self.retry_delay)

            self._retried += 1
            try:
                self.offset = self.get_offset()
            except TusCommunicationError as err:
                self._retry_or_cry(err)
            else:
                self._do_request()
        else:
            raise error











































class Uploader(BaseUploader):
    def upload(self, stop_at: Optional[int] = None, show_progress = True):
        """
        Perform file upload.

        Performs continous upload of chunks of the file. The size uploaded at each cycle is
        the value of the attribute 'chunk_size'.

        :Args:
            - stop_at (Optional[int]):
                Determines at what offset value the upload should stop. If not specified this
                defaults to the file size.
            - show_progress (False)
                Display current upload percentage while uploading
        """
        self.stop_at = stop_at or self.get_file_size()


        if show_progress:
            progress = tqdm (
                total=self.stop_at,
                unit="file",
                bar_format='{l_bar}{bar} | {n_fmt}/{total_fmt} Bytes [{elapsed}<{remaining}'
            )


        last_progress_offset = 0
        while self.offset < self.stop_at:
            self.upload_chunk()
            if show_progress:
                progress.update(self.offset - last_progress_offset)
                last_progress_offset = self.offset

        if show_progress:
            progress.close()

    def upload_chunk(self):
        """
        Upload chunk of file.
        """
        self._retried = 0
        if not self.url:
            self.set_url(self.create_url())
            self.offset = 0
        self._do_request()
        self.offset = int(self.request.response_headers.get('upload-offset'))

    @catch_requests_error
    def create_url(self):
        """
        Return upload url.

        Makes request to tus server to create a new upload url for the required file upload.
        """
        resp = requests.post(
            self.client.url, headers=self.get_url_creation_headers())
        url = resp.headers.get("location")
        if url is None:
            msg = 'Attempt to retrieve create file url with status {}'.format(
                resp.status_code)
            raise TusCommunicationError(msg, resp.status_code, resp.content)
        return urljoin(self.client.url, url)

    def _do_request(self):
        self.request = TusRequest(self)
        try:
            self.request.perform()
            _verify_upload(self.request)
        except TusUploadFailed as error:
            self._retry_or_cry(error)

    def _retry_or_cry(self, error):
        if self.retries > self._retried:
            time.sleep(self.retry_delay)

            self._retried += 1
            try:
                self.offset = self.get_offset()
            except TusCommunicationError as err:
                self._retry_or_cry(err)
            else:
                self._do_request()
        else:
            raise error



class AsyncUploader(BaseUploader):
    def __init__(self, *args, io_loop: Optional[asyncio.AbstractEventLoop] = None, **kwargs):
        self.io_loop = io_loop
        super().__init__(*args, **kwargs)

    async def upload(self, stop_at: Optional[int] = None):
        """
        Perform file upload.

        Performs continous upload of chunks of the file. The size uploaded at each cycle is
        the value of the attribute 'chunk_size'.

        :Args:
            - stop_at (Optional[int]):
                Determines at what offset value the upload should stop. If not specified this
                defaults to the file size.
        """
        self.stop_at = stop_at or self.get_file_size()
        while self.offset < self.stop_at:
            await self.upload_chunk()

    async def upload_chunk(self):
        """
        Upload chunk of file.
        """
        self._retried = 0
        if not self.url:
            self.set_url(await self.create_url())
            self.offset = 0
        await self._do_request()
        self.offset = int(self.request.response_headers.get('upload-offset'))

    async def create_url(self):
        """
        Return upload url.

        Makes request to tus server to create a new upload url for the required file upload.
        """
        try:
            async with aiohttp.ClientSession(loop=self.io_loop) as session:
                headers = self.get_url_creation_headers()
                async with session.post(self.client.url, headers=headers) as resp:
                    url = resp.headers.get("location")
                    if url is None:
                        msg = 'Attempt to retrieve create file url with status {}'.format(
                            resp.status_code)
                        raise TusCommunicationError(msg, resp.status, await resp.content.read())
                    return urljoin(self.client.url, url)
        except aiohttp.ClientError as error:
            raise TusCommunicationError(error)

    async def _do_request(self):
        self.request = AsyncTusRequest(self)
        try:
            await self.request.perform()
            _verify_upload(self.request)
        except TusUploadFailed as error:
            await self._retry_or_cry(error)

    async def _retry_or_cry(self, error):
        if self.retries > self._retried:
            await asyncio.sleep(self.retry_delay, loop=self.io_loop)

            self._retried += 1
            try:
                self.offset = self.get_offset()
            except TusCommunicationError as err:
                await self._retry_or_cry(err)
            else:
                await self._do_request()
        else:
            raise error
