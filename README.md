# paperlaas-translate

Standalone FastAPI webhook service that receives Paperless-ngx webhooks, translates the uploaded original document into one or more target languages, and uploads translated copies back into Paperless.

## Supported inputs

- `application/pdf` via `pdf2zh_next`
- `application/vnd.openxmlformats-officedocument.wordprocessingml.document` via `python-docx` + LLM translation
- `application/vnd.oasis.opendocument.text` via headless LibreOffice conversion to/from `.docx`
- `message/rfc822` by downloading the Paperless archived file from `/api/documents/{id}/download/` and translating that PDF
- `text/plain` via LLM translation

Legacy Word `.doc` files (`application/msword`) are detected but intentionally rejected unless you later add an external converter.

## Translation tags

The service looks for Paperless tags in this format:

- `translate to french`
- `translate to spanish`
- `translate to portuguese`
- `translate to english`
- `translate to german`

A document can contain multiple translation tags. One translated output is generated per target language.

## Environment

Copy `.env.example` to `.env` and set at least:

- `PAPERLESS_TOKEN`
- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `OPENAI_MODEL`

Optional PDF setting:

- `PDF2ZH_SOURCE_LANGUAGE`: defaults to the tool default. Set this if your PDFs are not primarily English.
- `PDF2ZH_WATERMARK_OUTPUT_MODE`: defaults to `no_watermark` so BabelDoc's header is not added. Set `watermarked` or `both` only if you explicitly want that output.

## Local development

```bash
uv sync --group dev
uv run uvicorn paperlaas_translate.main:app --reload --host 0.0.0.0 --port 8000
```

## Docker

Build the image:

```bash
docker build -t paperlaas-translate:latest .
```

Run it:

```bash
docker run --rm \
  --name paperlaas-translate \
  --env-file .env \
  -p 8000:8000 \
  paperlaas-translate:latest
```

## Deploy alongside Paperless

The repo includes a helper script that rebuilds and re-runs the container on the Paperless Docker network:

```bash
./scripts/deploy-paperless.sh
```

Defaults:

- network: `paperless_paperless`
- container: `paperlaas-translate`
- image: `paperlaas-translate:latest`
- env file: `.env`

You can override them with `DOCKER_NETWORK`, `CONTAINER_NAME`, `IMAGE_NAME`, and `ENV_FILE`.

## Webhook endpoint

- `POST /hooks/translate`

Expected form-data field:

- `url`: Paperless document URL such as `https://paperless.example.com/documents/2048/`
- `file`: original uploaded document from the Paperless webhook

The uploaded file is required. For most supported types it is used as the translation source. For `message/rfc822`, the service downloads the Paperless archived file and translates that PDF instead.

## Logging

Logs are emitted as plain text to stdout. Each job includes:

- request id
- document id
- MIME type
- requested target languages
- per-batch LLM request start, response timing, and token usage when the API returns it
- in `DEBUG`, the full LLM prompt payload sent for each batch
- per-language translation and upload status
- original tag update result

## Tests

```bash
uv run --group dev pytest
```
