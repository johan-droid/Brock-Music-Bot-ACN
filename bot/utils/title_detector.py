"""Smart title detection system with conflict resolution."""

import re
import logging
from typing import List, Dict, Any, Optional
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)

# Common words to strip for better matching
NOISE_WORDS = {
    'en': ['the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'from', 'up', 'about', 'into', 'through', 'during', 'before', 'after', 'above', 'below', 'between', 'under', 'again', 'further', 'then', 'once', 'here', 'there', 'when', 'where', 'why', 'how', 'all', 'any', 'both', 'each', 'few', 'more', 'most', 'other', 'some', 'such', 'no', 'nor', 'not', 'only', 'own', 'same', 'so', 'than', 'too', 'very', 'just', 'official', 'video', 'audio', 'remix', 'cover', 'version', 'live', 'studio', 'explicit', 'clean', 'radio', 'edit', 'extended', 'ft', 'feat', 'featuring', 'vs', 'x', 'and'],
    'ru': ['в', 'на', 'под', 'с', 'о', 'от', 'до', 'к', 'по', 'из', 'за', 'над', 'для', 'без', 'про', 'через', 'при', 'об', 'обо', 'во', 'ко', 'со', 'во', 'о', 'об', 'обо', 'это', 'как', 'так', 'что', 'чтобы', 'где', 'когда', 'почему', 'зачем', 'кто', 'который', 'которая', 'которое', 'которые', 'и', 'а', 'но', 'или', 'если', 'когда', 'хотя', 'потому', 'что', 'который', 'как', 'такой', 'такая', 'такое', 'такие', 'весь', 'вся', 'все', 'все', 'мой', 'моя', 'мое', 'мои', 'твой', 'твоя', 'твое', 'твои', 'его', 'ее', 'их', 'наш', 'наша', 'наше', 'наши', 'ваш', 'ваша', 'ваше', 'ваши', 'свой', 'своя', 'свое', 'свои', 'который', 'которая', 'которое', 'которые', 'официальный', 'видео', 'аудио', 'ремикс', 'кавер', 'версия', 'прямой', 'эфир', 'студия', 'явный', 'чистый', 'радио', 'редакция', 'расширенный', 'ft', 'feat', 'featuring', 'vs', 'x', 'и'],
}


def normalize_text(text: str) -> str:
    """Normalize text for comparison - handles Cyrillic and Latin."""
    if not text:
        return ""
    
    # Convert to lowercase
    text = text.lower()
    
    # Remove special characters but keep Cyrillic and Latin letters, numbers, spaces
    # Cyrillic range: \u0400-\u04FF, \u0500-\u052F
    # Latin: a-z
    # Numbers: 0-9
    text = re.sub(r'[^\w\s\u0400-\u04FF\u0500-\u052F]', ' ', text)
    
    # Remove extra whitespace
    text = ' '.join(text.split())
    
    return text.strip()


def strip_noise_words(text: str, lang: str = 'en') -> str:
    """Remove common noise words for better matching."""
    words = text.split()
    noise = NOISE_WORDS.get(lang, NOISE_WORDS['en'])
    cleaned = [w for w in words if w not in noise]
    return ' '.join(cleaned)


def detect_language(text: str) -> str:
    """Detect if text contains Cyrillic or is Latin."""
    cyrillic_pattern = re.compile('[\u0400-\u04FF\u0500-\u052F]')
    if cyrillic_pattern.search(text):
        return 'ru'
    return 'en'


def calculate_similarity(title1: str, title2: str) -> float:
    """Calculate similarity between two titles (0-1)."""
    norm1 = normalize_text(title1)
    norm2 = normalize_text(title2)
    
    if not norm1 or not norm2:
        return 0.0
    
    # Detect languages
    lang1 = detect_language(norm1)
    lang2 = detect_language(norm2)
    
    # If both have Cyrillic or both don't, compare directly
    # If mixed, normalize both
    
    # Remove noise words
    clean1 = strip_noise_words(norm1, lang1)
    clean2 = strip_noise_words(norm2, lang2)
    
    # Use SequenceMatcher for fuzzy matching
    base_similarity = SequenceMatcher(None, clean1, clean2).ratio()
    
    # Also check word-level overlap
    words1 = set(clean1.split())
    words2 = set(clean2.split())
    
    if words1 and words2:
        word_overlap = len(words1 & words2) / max(len(words1), len(words2))
        # Weighted combination
        return (base_similarity * 0.6) + (word_overlap * 0.4)
    
    return base_similarity


def is_title_conflict(title: str, existing_titles: List[str], threshold: float = 0.85) -> bool:
    """Check if a title conflicts (is too similar) with existing titles."""
    for existing in existing_titles:
        similarity = calculate_similarity(title, existing)
        if similarity >= threshold:
            return True
    return False


def find_similar_titles(title: str, candidates: List[Any], threshold: float = 0.75) -> List[Any]:
    """Find candidates that are similar to the given title (Handles Track objects and Dicts)."""
    similar = []
    for candidate in candidates:
        if hasattr(candidate, 'title'):
            candidate_title = candidate.title
        else:
            candidate_title = candidate.get('title', '')
            
        similarity = calculate_similarity(title, candidate_title)
        if similarity >= threshold:
            # Add similarity to object/dict for sorting
            if isinstance(candidate, dict):
                candidate['_similarity'] = similarity
            else:
                setattr(candidate, '_similarity', similarity)
            similar.append(candidate)
    
    # Sort by similarity (highest first)
    similar.sort(key=lambda x: getattr(x, '_similarity', 0) if not isinstance(x, dict) else x.get('_similarity', 0), reverse=True)
    return similar


def extract_artist_title(query: str) -> tuple:
    """Extract artist and title from query string."""
    # Common separators
    separators = [' - ', ' – ', ' — ', ' -', '- ', ' by ', ': ', '|']
    
    for sep in separators:
        if sep in query:
            parts = query.split(sep, 1)
            if len(parts) == 2:
                artist = parts[0].strip()
                title = parts[1].strip()
                return artist, title
    
    return None, query.strip()


def generate_search_variants(query: str) -> List[str]:
    """Generate search variants for better matching."""
    variants = [query]
    
    artist, title = extract_artist_title(query)
    if artist:
        # Add reversed format
        variants.append(f"{title} {artist}")
        # Add artist only
        variants.append(artist)
        # Add title only
        variants.append(title)
    
    # Add normalized version
    norm = normalize_text(query)
    if norm != query.lower():
        variants.append(norm)
    
    # Remove common suffixes/prefixes and add
    cleaned = re.sub(r'\s*\([^)]*\)\s*$', '', query)  # Remove parentheses at end
    cleaned = re.sub(r'\s*\[[^\]]*\]\s*$', '', cleaned)  # Remove brackets at end
    if cleaned != query:
        variants.append(cleaned.strip())
    
    return list(dict.fromkeys(variants))  # Remove duplicates while preserving order


class TitleConflictResolver:
    """Handles detection and resolution of title conflicts."""
    
    def __init__(self):
        self.search_results: Dict[str, List[Dict]] = {}
    
    async def search_with_conflicts(self, query: str, search_func, max_results: int = 5) -> Dict[str, Any]:
        """Search and detect if there are title conflicts.
        
        Returns:
            {
                'status': 'ok' | 'conflict' | 'not_found',
                'tracks': [...],  # All found tracks
                'selected': {...}, # Best match if status='ok'
                'conflicts': [...], # Similar tracks if status='conflict'
                'message': str
            }
        """
        # Generate search variants
        variants = generate_search_variants(query)
        all_results = []
        
        for variant in variants[:3]:  # Try first 3 variants
            try:
                results = await search_func(variant)
                if results:
                    if isinstance(results, list):
                        all_results.extend(results)
                    else:
                        all_results.append(results)
            except Exception as e:
                logger.debug(f"Search variant failed: {e}")
        
        if not all_results:
            return {
                'status': 'not_found',
                'tracks': [],
                'selected': None,
                'conflicts': [],
                'message': '❌ No songs found matching your query.'
            }
        
        # Remove duplicates by identity (URL, ID, or Source+Title)
        seen_identities = set()
        unique_results = []
        for track in all_results:
            # Generate a unique identity for this track
            identity = None
            if hasattr(track, 'track_id') and track.track_id:
                identity = f"{getattr(track, 'source', 'unknown')}:{track.track_id}"
            elif hasattr(track, 'stream_url') and track.stream_url:
                identity = track.stream_url
            elif hasattr(track, 'url') and track.url:
                identity = track.url
            elif isinstance(track, dict):
                identity = track.get('id') or track.get('url') or f"{track.get('source')}:{track.get('title')}"
            else:
                identity = f"{getattr(track, 'source', 'unknown')}:{getattr(track, 'title', 'unknown')}"
            
            if identity and identity not in seen_identities:
                seen_identities.add(identity)
                unique_results.append(track)
        
        if not unique_results:
            return {
                'status': 'not_found',
                'tracks': [],
                'selected': None,
                'conflicts': [],
                'message': '❌ No songs found matching your query.'
            }
        
        # Check for conflicts (similar titles)
        query_normalized = normalize_text(query)
        conflicts = find_similar_titles(query, unique_results, threshold=0.75)
        
        if len(conflicts) > 1:
            # Multi-match Logic:
            # 1. If the top result is a VERY strong match (> 0.95), pick it.
            # 2. If the top result is > 0.90 AND much better than the 2nd match, pick it.
            
            top_item = conflicts[0]
            top_sim = getattr(top_item, '_similarity', 0) if not isinstance(top_item, dict) else top_item.get('_similarity', 0)
            
            next_item = conflicts[1]
            next_sim = getattr(next_item, '_similarity', 0) if not isinstance(next_item, dict) else next_item.get('_similarity', 0)

            # Case 1: Near-perfect match
            if top_sim >= 0.95:
                return {
                    'status': 'ok',
                    'tracks': unique_results[:max_results],
                    'selected': top_item,
                    'conflicts': [],
                    'message': '✅ Found exact match.'
                }
            
            # Case 2: Good match and clearly better than other options
            if top_sim >= 0.90 and (top_sim - next_sim) >= 0.10:
                 return {
                    'status': 'ok',
                    'tracks': unique_results[:max_results],
                    'selected': top_item,
                    'conflicts': [],
                    'message': '✅ Found confident match.'
                }

            # Else: It's truly ambiguous, ask the user
            return {
                'status': 'conflict',
                'tracks': unique_results[:max_results],
                'selected': None,
                'conflicts': conflicts[:5],
                'message': f'🔍 Found {len(conflicts)} songs with similar titles. Please select:'
            }
        
        # Single clear result or no matches above 0.75
        best_match = conflicts[0] if conflicts else unique_results[0]
        
        return {
            'status': 'ok',
            'tracks': unique_results[:max_results],
            'selected': best_match,
            'conflicts': [],
            'message': '✅ Found matching song.'
        }
    
    def format_conflict_options(self, conflicts: List[Any]) -> str:
        """Format conflict options for display (Handles Track objects and Dicts)."""
        lines = ['🎵 **Multiple matches found. Which one?**\n']
        
        for i, track in enumerate(conflicts[:5], 1):
            if hasattr(track, 'title'):
                title = track.title
                artist = getattr(track, 'artist', getattr(track, 'uploader', 'Unknown'))
                duration = getattr(track, 'duration', 0)
                similarity = getattr(track, '_similarity', 0)
            else:
                title = track.get('title', 'Unknown')
                artist = track.get('uploader', track.get('artist', 'Unknown Artist'))
                duration = track.get('duration', 0)
                similarity = track.get('_similarity', 0)
            
            # Format duration
            mins, secs = divmod(int(duration), 60)
            duration_str = f"{mins}:{secs:02d}"
            
            match_indicator = "⭐" if similarity > 0.9 else ""
            
            lines.append(f"{i}. **{title}** {match_indicator}\n   👤 {artist} | ⏱ {duration_str}\n")
        
        lines.append("Reply with the number (1-5) to select, or 0 to cancel.")
        return '\n'.join(lines)


# ── Query Type Detection for Source Prioritization ─────────────────────────

# Keywords that indicate query types
_INDICIAN_ARTISTS = [
    # Common Indian artist name patterns
    'arijit', 'shreya', 'sonu', 'lata', 'kishore', 'mohammed', 'rafi', 'asha', 'kumar',
    'sanu', 'udit', 'alka', 'kavita', 'sunidhi', 'kailash', 'lucky', 'jubin', 'neha',
    'guru', 'badshah', 'yo yo', 'raftaar', 'divine', 'emway', 'mc stan', 'honey',
    'diljit', 'karan', 'jassie', 'b praak', 'jaani', 'akhil', 'ninja', 'amrit',
    'shankar', 'mahadevan', 'rehman', 'rahman', 'ilaiyaraaja', 'ar rahman', 'ilayaraja',
    'anirudh', 'gv prakash', 'hiphop', 'tamizha', 'adhi', 'vijay', 'ajith', 'suriya',
    'dhanush', 'simbu', 'yuvan', 'harris', 'jayaraj', 'deva', 'mano', 's janaki',
    'spb', 'balasubrahmanyam', 'chitra', 'susheela', 'yesudas', 'jayachandran',
    'vani', 'jairam', 'malaysia', 'vasudevan', 'unnikrishnan', 'nithyashree',
    'bombay', 'jayashri', 'k s chithra', 'madhu balakrishnan', 'madhusoodanan',
]

_ELECTRONIC_KEYWORDS = [
    'remix', 'bootleg', 'mashup', 'edit', 'flip', 'rework', 'vip', 'extended',
    'radio edit', 'club mix', 'dubstep', 'house', 'techno', 'trance', 'edm',
    'bass', 'trap', 'dub', 'electro', 'synthwave', 'lofi', 'lo-fi', 'chillout',
    'progressive', 'deep house', 'future house', 'big room', 'hardstyle',
    'drum and bass', 'dnb', 'jungle', 'garage', 'grime', 'bassline',
]

_HIPHOP_KEYWORDS = [
    'rap', 'hip hop', 'hiphop', 'freestyle', 'diss', 'cypher', 'trap',
    'drill', 'mumble', 'boom bap', 'old school', 'underground', 'grime',
]

_LIVE_KEYWORDS = [
    'live', 'concert', 'unplugged', 'acoustic', 'studio', 'session',
    'cover', 'tribute', 'karaoke', 'instrumental',
]

_OFFICIAL_KEYWORDS = [
    'official', 'official video', 'official audio', 'music video', 'mv',
    'lyric', 'lyrics video', 'audio', 'hd', '4k', 'remastered',
]


def detect_query_type(query: str) -> Dict[str, float]:
    """
    Detect the type of music query to inform source prioritization.
    
    Returns a dict of category scores (0.0 - 1.0):
    - indian: Likely Indian/Bollywood music
    - electronic: Electronic, remixes, EDM
    - hiphop: Hip-hop, rap, trap
    - live_acoustic: Live performances, acoustic versions
    - official: Official releases (prioritize YT Music, Spotify)
    - western_pop: Western pop/rock (default high for YT Music)
    """
    if not query:
        return {"western_pop": 0.8, "indian": 0.3, "electronic": 0.5}
    
    query_lower = query.lower()
    query_words = set(query_lower.split())
    
    scores = {
        "indian": 0.0,
        "electronic": 0.0,
        "hiphop": 0.0,
        "live_acoustic": 0.0,
        "official": 0.0,
        "western_pop": 0.5,  # Base score
    }
    
    # Check for Indian artist names
    for artist in _INDICIAN_ARTISTS:
        if artist in query_lower:
            scores["indian"] = 1.0
            break
    
    # Check for electronic keywords
    for keyword in _ELECTRONIC_KEYWORDS:
        if keyword in query_lower:
            scores["electronic"] = min(1.0, scores["electronic"] + 0.3)
    
    # Check for hip-hop keywords
    for keyword in _HIPHOP_KEYWORDS:
        if keyword in query_lower:
            scores["hiphop"] = min(1.0, scores["hiphop"] + 0.4)
    
    # Check for live/acoustic keywords
    for keyword in _LIVE_KEYWORDS:
        if keyword in query_lower:
            scores["live_acoustic"] = min(1.0, scores["live_acoustic"] + 0.3)
    
    # Check for official keywords
    for keyword in _OFFICIAL_KEYWORDS:
        if keyword in query_lower:
            scores["official"] = min(1.0, scores["official"] + 0.3)
    
    # Language detection for Indian music
    # Hindi songs often have specific patterns
    hindi_indicators = ['है', 'का', 'की', 'के', 'में', 'से', 'को', 'ने', 'हैं']
    if any(ind in query for ind in hindi_indicators):
        scores["indian"] = 1.0
    
    # If no strong signals, boost western_pop
    if sum(scores.values()) < 1.0:
        scores["western_pop"] = 0.8
    
    logger.debug(f"Query type detection for '{query[:40]}...': {scores}")
    return scores


def get_source_weights_for_query(query: str) -> Dict[str, float]:
    """
    Get dynamic source weights based on query type.
    Higher weight = higher priority (lower rank number).
    """
    query_type = detect_query_type(query)
    
    # Base weights
    weights = {
        "jiosaavn": 0.7,
        "soundcloud": 0.6,
        "ytmusic": 0.8,
        "youtube": 0.5,
        "audiomack": 0.5,
        "spotify": 0.9,
    }
    
    # Adjust based on query type
    if query_type["indian"] > 0.7:
        weights["jiosaavn"] = 1.0
        weights["ytmusic"] = 0.7
        weights["soundcloud"] = 0.4
    
    if query_type["electronic"] > 0.6:
        weights["soundcloud"] = 1.0
        weights["audiomack"] = 0.8
        weights["jiosaavn"] = 0.4
    
    if query_type["hiphop"] > 0.6:
        weights["audiomack"] = 1.0
        weights["soundcloud"] = 0.9
        weights["ytmusic"] = 0.6
    
    if query_type["official"] > 0.6:
        weights["ytmusic"] = 1.0
        weights["spotify"] = 0.95
        weights["jiosaavn"] = 0.6
    
    if query_type["live_acoustic"] > 0.5:
        # Live versions often on YouTube
        weights["youtube"] = 0.8
        weights["ytmusic"] = 0.7
    
    return weights


# Global resolver instance
conflict_resolver = TitleConflictResolver()
