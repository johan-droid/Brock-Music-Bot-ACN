import re

with open("bot/core/music_backend.py", "r") as f:
    content = f.read()

# Add imports
if "from bot.utils.circuit_breaker import source_health_tracker" not in content:
    content = content.replace(
        "import bot.utils.database as database_module",
        "import bot.utils.database as database_module\nfrom bot.utils.circuit_breaker import source_health_tracker\nfrom bot.utils.errors import PreviewOnlyError, SourceExhaustedError, FallbackExhaustedError, BotDetectionError"
    )

# Extractors map for dynamic lookup
extractors_map_code = """
    @property
    def extractors_map(self):
        return {
            "youtube_wrapper": youtube_wrapper_extractor,
            "youtube": youtube_extractor,
            "jiosaavn_wrapper": jiosaavn_wrapper_extractor,
            "jiosaavn": jiosaavn_extractor,
            "deezer": deezer_extractor,
            "vk": vk_extractor
        }

"""

if "def extractors_map" not in content:
    content = content.replace("async def init(self):", extractors_map_code + "    async def init(self):")

# Update search method
search_method_start = content.find("async def search(self, query: str, limit: int = 5) -> List[Track]:")
search_method_end = content.find("async def get_stream_payload", search_method_start)

old_search = content[search_method_start:search_method_end]

new_search = """async def search(self, query: str, limit: int = 5) -> List[Track]:
        query = query.strip()
        if not query:
            return []

        from config import config

        sorted_sources = await source_health_tracker.get_sorted_sources()
        if not sorted_sources:
            # Fallback if tracker is empty
            sorted_sources = ["youtube_wrapper", "youtube", "jiosaavn_wrapper", "jiosaavn", "deezer", "vk"]

        tracks = []

        # If parallel search
        if config.PARALLEL_SEARCH:
            tasks = []
            for src_name in sorted_sources:
                extractor = self.extractors_map.get(src_name)
                if extractor and hasattr(extractor, "search"):
                    tasks.append(self._search_with_extractor(extractor, query, limit, src_name))

            if config.PRIORITIZE_EXTRACTORS:
                tasks.append(self._search_index(query, limit))

            results = await asyncio.gather(*tasks, return_exceptions=True)

            combined = []
            seen = set()

            for res in results:
                if isinstance(res, Exception) or not res:
                    continue
                for t in res:
                    norm = re.sub(r'[^a-zA-Z0-9]', '', f"{t.title}{t.artist}").lower()
                    if norm not in seen:
                        seen.add(norm)
                        combined.append(t)

            tracks = combined[:limit]
        else:
            # Sequential search using health tracker
            if not config.PRIORITIZE_EXTRACTORS:
                tracks = await self._search_index(query, limit)

            if not tracks:
                for src_name in sorted_sources:
                    extractor = self.extractors_map.get(src_name)
                    if extractor and hasattr(extractor, "search"):
                        try:
                            tracks = await self._search_with_extractor(extractor, query, limit, src_name.split("_")[0])
                            if tracks:
                                break
                        except Exception as e:
                            logger.debug(f"Search failed for {src_name}: {e}")

            if not tracks and config.PRIORITIZE_EXTRACTORS:
                tracks = await self._search_index(query, limit)

        if tracks and len(_background_tasks) < _MAX_BACKGROUND_TASKS:
            task = asyncio.create_task(self._save_to_index(tracks))
            _background_tasks.add(task)
            task.add_done_callback(_background_tasks.discard)

        return tracks

    """

content = content.replace(old_search, new_search)


# Update get_stream_payload
payload_method_start = content.find("async def get_stream_payload")
payload_method_end = content.find("async def _resolve_from_search", payload_method_start)

old_payload = content[payload_method_start:payload_method_end]

new_payload = """async def get_stream_payload(self, track: Track) -> Optional[Dict[str, Any]]:
        if not track:
            return None

        # Check direct URL
        if track.stream_url and track.stream_url.startswith("http") and _infer_source_from_url(track.stream_url) == "direct":
            return self._build_payload(track, None, "direct")

        resolved = None
        source = track.source or "unknown"

        # Primary source extraction
        if source != "unknown":
            primary_wrapper = f"{source}_wrapper"
            primary_direct = source

            for src_name in [primary_wrapper, primary_direct]:
                extractor = self.extractors_map.get(src_name)
                if extractor and hasattr(extractor, "extract"):
                    try:
                        resolved = await extractor.extract(track.track_id)
                        if resolved:
                            source = src_name.split("_")[0]
                            break
                    except PreviewOnlyError:
                        logger.warning(f"Preview only error from {src_name}, falling back...")
                        resolved = None
                    except BotDetectionError:
                        logger.warning(f"Bot detection error from {src_name}, falling back...")
                        resolved = None
                    except Exception as e:
                        logger.debug(f"Extraction failed for {src_name}: {e}")
                        resolved = None

        # Intelligent Fallback Chain
        if not resolved and track.track_id:
            logger.info(f"Primary extraction failed for {track.title}, engaging intelligent fallback...")

            sorted_sources = await source_health_tracker.get_sorted_sources()
            if not sorted_sources:
                sorted_sources = ["youtube_wrapper", "youtube", "jiosaavn_wrapper", "jiosaavn", "deezer", "vk"]

            for src_name in sorted_sources:
                # Skip what we already tried
                if src_name in [f"{track.source}_wrapper", track.source]:
                    continue

                extractor = self.extractors_map.get(src_name)
                if extractor and hasattr(extractor, "extract"):
                    try:
                        # Attempt to use the same track_id. Note: cross-platform ID matching is rare,
                        # but if an extractor handles standard IDs, it might work. Otherwise, we fallback to search.
                        # Realistically, if track_id is a YT id, Jiosaavn won't resolve it.
                        # We will skip direct extraction and go to search fallback below.
                        pass
                    except Exception:
                        pass

        # FINAL FALLBACK: Search for the track by title across healthy sources
        if not resolved and track.title:
            logger.info(f"ID-based extraction failed, trying search fallback for '{track.title}'")
            search_query = f"{track.title} {track.artist}" if track.artist and track.artist != "Unknown Artist" else track.title

            sorted_sources = await source_health_tracker.get_sorted_sources()
            for src_name in sorted_sources:
                extractor = self.extractors_map.get(src_name)
                if extractor and hasattr(extractor, "search") and hasattr(extractor, "extract"):
                    try:
                        search_res = await extractor.search(search_query, limit=1)
                        if search_res:
                            track_id = search_res[0].get("id")
                            if track_id:
                                resolved = await extractor.extract(track_id)
                                if resolved:
                                    logger.info(f"Fallback search success via {src_name} for {track.title}")
                                    source = src_name.split("_")[0]
                                    break
                    except PreviewOnlyError:
                        logger.warning(f"Preview only error during fallback search on {src_name}")
                        continue
                    except BotDetectionError:
                        logger.warning(f"Bot detection during fallback search on {src_name}")
                        continue
                    except Exception as e:
                        logger.debug(f"Fallback search failed for {src_name}: {e}")
                        continue

        if resolved:
            payload = self._build_payload(track, resolved, source)
            if payload["url"] and not _looks_like_unsupported_page_url(payload["url"]):
                logger.info(f"Successfully resolved stream URL for {track.title} from {source}")
                return payload

        if track.stream_url and track.stream_url.startswith("http") and _infer_source_from_url(track.stream_url) == "direct":
            return self._build_payload(track, None, source or "direct")

        # Raise a user-friendly error if we exhaust all fallbacks
        raise FallbackExhaustedError("Could not find a working stream for this track across all sources.")

    """

content = content.replace(old_payload, new_payload)


with open("bot/core/music_backend.py", "w") as f:
    f.write(content)
