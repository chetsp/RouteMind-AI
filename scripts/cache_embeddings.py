"""Download and checksum-verify the pinned Chroma MiniLM weights at image build."""
import os
from pathlib import Path
from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2

if __name__ == '__main__':
    embed = ONNXMiniLM_L6_V2(preferred_providers=['CPUExecutionProvider'])
    embed.DOWNLOAD_PATH = Path(os.environ['MODEL_CACHE_DIR']) / 'all-MiniLM-L6-v2'
    embed(['freight planning'])
    print('Verified MiniLM cached, SHA256:',embed._MODEL_SHA256)
