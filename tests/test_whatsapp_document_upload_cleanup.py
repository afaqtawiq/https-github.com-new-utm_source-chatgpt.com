"""Cancellation must close private multipart files after they roll onto disk."""
import anyio
import pytest
from fastapi import HTTPException
from starlette.datastructures import Headers, UploadFile
import starlette.formparsers as formparsers

from app import whatsapp_inbox as inbox


def test_cancelled_read_closes_rolled_private_upload(monkeypatch):
    # Synthetic bytes only: document_form checks the signature; parsing the PDF
    # and storing a draft happen later and must never be reached in this test.
    body = b''.join(
        b'--cleanup-boundary\r\nContent-Disposition: form-data; name="'
        + name.encode() + b'"\r\n\r\n' + value.encode() + b'\r\n'
        for name, value in (
            ('csrf', 'synthetic-csrf'),
            ('conversation', 'synthetic-conversation'),
            ('caption', 'Synthetic caption'),
        )
    )
    body += (
        b'--cleanup-boundary\r\n'
        b'Content-Disposition: form-data; name="attachment"; filename="synthetic.pdf"\r\n'
        b'Content-Type: application/pdf\r\n\r\n%PDF-'
        + b'x' * (1100 * 1024)
        + b'\r\n--cleanup-boundary--\r\n'
    )

    class Request:
        headers = Headers({
            'content-type': 'multipart/form-data; boundary=cleanup-boundary',
        })

        async def stream(self):
            for offset in range(0, len(body), 65536):
                yield body[offset:offset + 65536]
                await anyio.sleep(0)

    private_files = []
    create_tempfile = formparsers.SpooledTemporaryFile

    def capture_tempfile(*args, **kwargs):
        temporary = create_tempfile(*args, **kwargs)
        private_files.append(temporary)
        return temporary

    monkeypatch.setattr(formparsers, 'SpooledTemporaryFile', capture_tempfile)

    async def cancel_after_parse():
        reads = []
        with anyio.CancelScope() as scope:
            async def cancelled_read(upload, size=-1):
                # This point is reached after parsing has returned FormData.
                # AnyIO cancellation also interrupts its asynchronous close.
                reads.append(upload)
                assert upload.file._rolled
                scope.cancel()
                await anyio.sleep(0)
                raise AssertionError('The cancelled read unexpectedly completed')

            monkeypatch.setattr(UploadFile, 'read', cancelled_read)
            await inbox.document_form(Request(), {'csrf': 'synthetic-csrf'})

        assert scope.cancelled_caught
        assert len(reads) == 1

    try:
        anyio.run(cancel_after_parse)
        assert len(private_files) == 1
        assert all(temporary.closed for temporary in private_files)
    finally:
        # Leave no synthetic file open even if this regression fails.
        for temporary in private_files:
            temporary.close()


@pytest.mark.parametrize('header_values, body, expected_status', [
    ({}, b'', 415),
    ({'content-type': 'multipart/form-data; boundary=b'}, b'garbage', 400),
    (
        {'content-type': 'multipart/form-data; boundary=b'},
        b'--b\r\nBad header\r\n\r\nx\r\n--b--\r\n',
        400,
    ),
])
def test_malformed_multipart_is_client_error(header_values, body, expected_status):
    class Request:
        headers = Headers(header_values)

        async def stream(self):
            yield body

    async def parse():
        with pytest.raises(HTTPException) as caught:
            await inbox.document_form(Request(), {'csrf': 'synthetic-csrf'})
        assert caught.value.status_code == expected_status

    anyio.run(parse)
