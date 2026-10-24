"""
Medicine Service: Verified local medicine catalogue search and ambiguity verification.
Provenance: WHO Model List 2023 / EMS Formulary v1.2.
"""

import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import json
import re
from rapidfuzz import process, fuzz
from backend.database.db import get_db_connection

def compute_phonetic_code(word):
    """
    Compute standard Soundex phonetic representation for phonetic similarity matching.
    Helps match phonetically similar speech errors (e.g. 'paracetemol' -> P623).
    """
    if not word:
        return ""
    clean = re.sub(r'[^A-Za-z]', '', word).upper()
    if not clean:
        return ""

    # Metaphone-style prefix reduction
    clean = clean.replace("PH", "F").replace("KN", "N").replace("GN", "N").replace("WR", "R")
    first_char = clean[0]

    soundex_map = {
        "B": "1", "F": "1", "P": "1", "V": "1",
        "C": "2", "G": "2", "J": "2", "K": "2", "Q": "2", "S": "2", "X": "2", "Z": "2",
        "D": "3", "T": "3",
        "L": "4",
        "M": "5", "N": "5",
        "R": "6"
    }

    code = [first_char]
    for char in clean[1:]:
        digit = soundex_map.get(char, "0")
        if digit != "0" and digit != code[-1]:
            code.append(digit)

    return ("".join(code) + "0000")[:4]

ROUTE_EQUIVALENCE = {
    "oral": {"oral", "orally", "po", "p.o.", "p o", "by mouth", "per os", "swallowed", "வாய்வழியாக", "குடிக்க", "முழுங்க", "வாய் வழி", "मुंह से", "ओरल"},
    "chewable": {"chewable", "chewed", "oral", "orally", "po", "by mouth"},
    "iv": {"iv", "i.v.", "i v", "intravenous", "intravenously", "iv push", "iv drip", "iv infusion", "via iv", "நரம்பு வழியாக", "ஐவி", "नस से", "आईवी"},
    "im": {"im", "i.m.", "i m", "intramuscular", "intramuscularly", "தசை வழியாக", "ஐஎம்", "मांसपेशी में", "आईएम"},
    "sublingual": {"sublingual", "sublingually", "sl", "s.l.", "s l", "under the tongue", "நாக்கின் அடியில்", "எஸ்எல்", "जीभ के नीचे", "एसएल"},
    "in": {"in", "i.n.", "i n", "intranasal", "intranasally", "nasal", "nasal spray", "மூக்கு வழியாக", "நாசி ஸ்ப்ரே", "नाक से"},
    "intranasal": {"in", "i.n.", "i n", "intranasal", "intranasally", "nasal", "nasal spray", "மூக்கு வழியாக", "நாசி ஸ்ப்ரே", "नाक से"},
    "inhaled": {"inhaled", "inhalation", "inhaler", "puff", "puffs", "nebulized", "nebulizer", "via nebulizer", "inhaled/nebulized", "சுவாசம் வழியாக", "இன்ஹேலர்", "நெபுலைசர்", "சாंस द्वारा", "इन्हेलर", "नेबुलाइजर"},
    "nebulized": {"inhaled", "inhalation", "inhaler", "puff", "puffs", "nebulized", "nebulizer", "via nebulizer", "inhaled/nebulized", "சுவாசம் வழியாக", "இன்ஹேலர்", "நெபுலைசர்", "சாंस द्वारा", "इन्हेलर", "नेबुलाइजर"},
    "inhaled/nebulized": {"inhaled", "inhalation", "inhaler", "puff", "puffs", "nebulized", "nebulizer", "via nebulizer", "inhaled/nebulized", "சுவாசம் வழியாக", "இன்ஹேலர்", "நெபுலைசர்", "சாंस द्वारा", "इन्हेलर", "नेबुलाइजर"},
    "sc": {"sc", "s.c.", "s c", "sq", "s.q.", "s q", "sub-q", "subq", "subcutaneous", "subcutaneously"},
    "io": {"io", "i.o.", "i o", "intraosseous", "intraosseously", "எலும்பு வழியாக", "हड्डी से", "आईओ"},
    "pr": {"pr", "p.r.", "p r", "per rectum", "rectal", "rectally", "மலக்குடல் வழியாக", "गुदा से"},
    "transdermal": {"transdermal", "transdermally", "topical", "topically", "patch"},
    "topical": {"topical", "topically", "transdermal", "transdermally", "patch"},
    "buccal": {"buccal", "buccally"},
    "odt": {"odt", "orally disintegrating", "oral"}
}

def check_route_match(extracted_route, standard_routes):
    """
    Check if an extracted route matches any standard catalogue routes,
    supporting standard clinical phrases, synonyms, abbreviations, and adverb forms.
    """
    if not extracted_route or not standard_routes:
        return False
    norm_r = str(extracted_route).lower().strip().strip(".,;:?!'\"")
    norm_r_nodots = re.sub(r"[.\s]+", " ", norm_r)
    norm_r_clean = norm_r.replace(".", "").strip()
    norm_standards = [s.lower().strip() for s in standard_routes]

    # Direct equality or substring check (preserves existing behavior)
    for sr in norm_standards:
        if (norm_r == sr or norm_r in sr or sr in norm_r or 
            norm_r_clean == sr or norm_r_clean in sr or sr in norm_r_clean):
            return True

    # Equivalence mapping check
    for sr in norm_standards:
        sr_equiv = ROUTE_EQUIVALENCE.get(sr, set())
        if norm_r in sr_equiv or norm_r_nodots in sr_equiv or norm_r_clean in sr_equiv:
            return True
        for candidate in (norm_r, norm_r_nodots, norm_r_clean):
            r_equiv = ROUTE_EQUIVALENCE.get(candidate, set())
            if sr in r_equiv or (r_equiv and sr_equiv and r_equiv.intersection(sr_equiv)):
                return True

    return False

class MedicineService:
    @classmethod
    def get_all_medicines(cls):
        """Fetch all verified medicines from SQLite."""
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM medicine_catalogue ORDER BY canonical_name ASC;")
            rows = cursor.fetchall()
            results = []
            for r in rows:
                item = dict(r)
                item["aliases"] = json.loads(item["aliases"])
                item["standard_routes"] = json.loads(item["standard_routes"])
                item["standard_units"] = json.loads(item["standard_units"])
                item["typical_doses"] = json.loads(item["typical_doses"])
                results.append(item)
            return results
        finally:
            conn.close()

    @classmethod
    def compare_strength_and_route(cls, canonical_name, strength=None, route=None):
        """
        Compare extracted strength and route against verified catalogue specifications.
        Does not recommend medications or infer missing parameters.
        """
        all_meds = {m["canonical_name"].lower(): m for m in cls.get_all_medicines()}
        med = all_meds.get(canonical_name.lower())
        if not med:
            return {
                "strength_checked": False,
                "route_checked": False,
                "notes": "Medicine not found in local catalogue."
            }

        typical_doses = [d.lower().replace(" ", "") for d in med.get("typical_doses", [])]
        standard_routes = [r.lower() for r in med.get("standard_routes", [])]

        strength_match = None
        strength_note = "Strength not specified."
        if strength:
            norm_str = str(strength).lower().replace(" ", "")
            strength_match = any(norm_str in td or td in norm_str for td in typical_doses)
            if strength_match:
                strength_note = f"Strength '{strength}' matches standard formulary dose."
            else:
                strength_note = f"Strength '{strength}' differs from typical pre-hospital doses ({', '.join(med['typical_doses'])})."

        route_match = None
        route_note = "Route not specified."
        if route:
            route_match = check_route_match(route, med.get("standard_routes", []))
            if route_match:
                route_note = f"Route '{route}' matches standard administration route."
            else:
                route_note = f"Route '{route}' is non-standard for {med['canonical_name']} (Standard: {', '.join(med['standard_routes'])})."

        return {
            "strength_checked": bool(strength),
            "strength_match": strength_match,
            "strength_note": strength_note,
            "route_checked": bool(route),
            "route_match": route_match,
            "route_note": route_note,
            "pediatric_warning": bool(med.get("pediatric_warning")),
            "standard_routes": med.get("standard_routes", []),
            "typical_doses": med.get("typical_doses", [])
        }

    @classmethod
    def match_medicine(cls, query_text, strength=None, route=None):
        """
        Match a query text against verified medicines using dual spelling and phonetic similarity.
        Compares strength and route when provided.
        Returns explicit candidate matches with uncertainty explanations.
        """
        if not query_text or not query_text.strip():
            return {
                "status": "UNIDENTIFIED_NEEDS_VERIFICATION",
                "matched_canonical": None,
                "confidence_score": 0.0,
                "candidates": [],
                "pediatric_warning": False,
                "requires_confirmation": True,
                "uncertainty_explanation": "No medicine query text supplied.",
                "provenance": "None"
            }

        q = query_text.strip().strip(".,;:?!'\"").lower()
        q_phonetic = compute_phonetic_code(q)
        medicines = cls.get_all_medicines()

        # Step 1: Check Exact Canonical Match
        for med in medicines:
            if med["canonical_name"].lower() == q:
                comparison = cls.compare_strength_and_route(med["canonical_name"], strength, route)
                return {
                    "status": "EXACT",
                    "matched_canonical": med["canonical_name"],
                    "confidence_score": 100.0,
                    "phonetic_match": True,
                    "candidates": [{
                        "canonical_name": med["canonical_name"],
                        "score": 100.0,
                        "category": med["category"],
                        "provenance": med["provenance"],
                        "phonetic_code": compute_phonetic_code(med["canonical_name"])
                    }],
                    "strength_comparison": comparison,
                    "pediatric_warning": bool(med["pediatric_warning"]),
                    "requires_confirmation": False,
                    "uncertainty_explanation": "Exact match against canonical catalogue entry.",
                    "provenance": med["provenance"]
                }

        # Step 2: Check Exact Verified Alias Match
        for med in medicines:
            for alias in med["aliases"]:
                if alias.lower() == q:
                    comparison = cls.compare_strength_and_route(med["canonical_name"], strength, route)
                    return {
                        "status": "ALIAS",
                        "matched_canonical": med["canonical_name"],
                        "alias_matched": alias,
                        "confidence_score": 98.0,
                        "phonetic_match": True,
                        "candidates": [{
                            "canonical_name": med["canonical_name"],
                            "matched_alias": alias,
                            "score": 98.0,
                            "category": med["category"],
                            "provenance": med["provenance"],
                            "phonetic_code": compute_phonetic_code(alias)
                        }],
                        "strength_comparison": comparison,
                        "pediatric_warning": bool(med["pediatric_warning"]),
                        "requires_confirmation": False,
                        "uncertainty_explanation": f"Exact match with verified synonym '{alias}'.",
                        "provenance": med["provenance"]
                    }

        # Step 3: Dual Spelling + Phonetic Similarity Ranking
        candidate_pool = {}
        for med in medicines:
            canonical_ratio = fuzz.ratio(q, med["canonical_name"].lower())
            token_ratio = fuzz.token_sort_ratio(q, med["canonical_name"].lower())
            best_med_score = max(canonical_ratio, token_ratio)

            # Check phonetic match
            med_phonetic = compute_phonetic_code(med["canonical_name"])
            phonetic_match = (q_phonetic == med_phonetic)
            if phonetic_match and best_med_score < 80:
                best_med_score += 12.0  # Phonetic boost for auditory speech mistranscriptions

            # Score aliases
            for alias in med["aliases"]:
                ar = fuzz.ratio(q, alias.lower())
                tr = fuzz.token_sort_ratio(q, alias.lower())
                alias_phonetic = compute_phonetic_code(alias)
                alias_score = max(ar, tr)
                if q_phonetic == alias_phonetic and alias_score < 80:
                    alias_score += 12.0
                if alias_score > best_med_score:
                    best_med_score = alias_score
                    phonetic_match = (q_phonetic == alias_phonetic)

            if best_med_score >= 50.0:
                comparison = cls.compare_strength_and_route(med["canonical_name"], strength, route)
                candidate_pool[med["canonical_name"]] = {
                    "canonical_name": med["canonical_name"],
                    "score": round(min(best_med_score, 99.0), 1),
                    "phonetic_match": phonetic_match,
                    "phonetic_code": med_phonetic,
                    "category": med["category"],
                    "pediatric_warning": bool(med["pediatric_warning"]),
                    "strength_comparison": comparison,
                    "provenance": med["provenance"]
                }

        ranked_candidates = sorted(candidate_pool.values(), key=lambda x: x["score"], reverse=True)

        if not ranked_candidates:
            return {
                "status": "UNIDENTIFIED_NEEDS_VERIFICATION",
                "matched_canonical": None,
                "confidence_score": 0.0,
                "candidates": [],
                "pediatric_warning": False,
                "requires_confirmation": True,
                "uncertainty_explanation": f"No plausible candidate found in catalogue for '{query_text}'. Explicit human entry required.",
                "provenance": "Local Catalogue v1.2.0"
            }

        top_candidate = ranked_candidates[0]

        # Ambiguity detection: if top 2 candidates are close in score
        if len(ranked_candidates) > 1:
            diff = top_candidate["score"] - ranked_candidates[1]["score"]
            if diff < 15.0 or top_candidate["score"] < 90.0:
                return {
                    "status": "AMBIGUOUS",
                    "matched_canonical": top_candidate["canonical_name"],
                    "confidence_score": top_candidate["score"],
                    "candidates": ranked_candidates[:4],
                    "pediatric_warning": top_candidate["pediatric_warning"],
                    "requires_confirmation": True,
                    "uncertainty_explanation": f"Multiple plausible medicines ({top_candidate['canonical_name']} vs {ranked_candidates[1]['canonical_name']}). Human confirmation mandatory.",
                    "strength_comparison": top_candidate.get("strength_comparison"),
                    "provenance": top_candidate["provenance"]
                }

        # Single fuzzy suggestion
        return {
            "status": "FUZZY_SUGGESTION",
            "matched_canonical": top_candidate["canonical_name"],
            "confidence_score": top_candidate["score"],
            "candidates": ranked_candidates[:3],
            "pediatric_warning": top_candidate["pediatric_warning"],
            "requires_confirmation": True,
            "uncertainty_explanation": f"Candidate suggested with {top_candidate['score']}% similarity. Human confirmation required.",
            "strength_comparison": top_candidate.get("strength_comparison"),
            "provenance": top_candidate["provenance"]
        }
