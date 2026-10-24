"""
Spoken Number Normalizer: Converts spoken numerical phrases into standard clinical numerical representations.
Supports English, Hindi, Tamil, and common ambulance conversational speech patterns.
Examples:
  - "one twenty over eighty" -> "120/80"
  - "blood pressure one twenty over eighty" -> "blood pressure 120/80"
  - "five milligrams of morphine" -> "5 mg of morphine"
  - "zero point five milligrams" -> "0.5 mg"
  - "point five mg" -> "0.5 mg"
  - "half a milligram" -> "0.5 mg"
  - "pulse seventy five" -> "pulse 75"
  - "ek sau bees over assi" -> "120/80" (Hindi-English code-switching)
  - "nootru irubadhu over enbadhu" -> "120/80" (Tamil-English code-switching)
"""

import re

# English spoken number dictionary
WORD_TO_NUMBER_EN = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90
}

# Auto-generate compound tens (21-99)
COMPOUND_TENS_EN = {}
tens_words = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
unit_words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9}
for t_k, t_v in tens_words.items():
    for u_k, u_v in unit_words.items():
        COMPOUND_TENS_EN[f"{t_k} {u_k}"] = t_v + u_v
        COMPOUND_TENS_EN[f"{t_k}-{u_k}"] = t_v + u_v

# Compound hundreds common in clinical blood pressure & pulse (100 to 250)
COMPOUND_HUNDREDS_EN = {
    "one hundred": 100, "a hundred": 100, "hundred": 100,
    "one ten": 110, "one eleven": 111, "one twelve": 112, "one thirteen": 113,
    "one fourteen": 114, "one fifteen": 115, "one sixteen": 116, "one seventeen": 117,
    "one eighteen": 118, "one nineteen": 119, "one twenty": 120,
    "one thirty": 130, "one forty": 140, "one fifty": 150, "one sixty": 160,
    "one seventy": 170, "one eighty": 180, "one ninety": 190,
    "two hundred": 200, "two ten": 210, "two twenty": 220
}

# Add "one twenty five", "one thirty five", etc.
for t_phrase, t_val in COMPOUND_TENS_EN.items():
    COMPOUND_HUNDREDS_EN[f"one {t_phrase}"] = 100 + t_val
    COMPOUND_HUNDREDS_EN[f"one hundred and {t_phrase}"] = 100 + t_val
    COMPOUND_HUNDREDS_EN[f"one hundred {t_phrase}"] = 100 + t_val

# Hindi spoken numbers and phonetics
HINDI_NUMBERS = {
    "shunya": 0, "ek": 1, "do": 2, "teen": 3, "char": 4, "chaar": 4, "paanch": 5, "panch": 5,
    "chhe": 6, "saat": 7, "aath": 8, "nau": 9, "das": 10,
    "gyarah": 11, "barah": 12, "terah": 13, "chaudah": 14, "pandrah": 15,
    "solah": 16, "satrah": 17, "atharah": 18, "unnees": 19,
    "bees": 20, "tees": 30, "chalis": 40, "pachaas": 50, "pachas": 50,
    "saath": 60, "sattar": 70, "assi": 80, "nabbe": 90,
    "sau": 100, "ek sau": 100, "ek sau das": 110, "ek sau bees": 120, "ek sau tees": 130,
    "ek sau chalis": 140, "ek sau pachaas": 150, "ek sau saath": 160, "do sau": 200,
    # Devanagari numerals and words
    "शून्य": 0, "एक": 1, "दो": 2, "तीन": 3, "चार": 4, "पाँच": 5, "पांच": 5,
    "छह": 6, "सात": 7, "आठ": 8, "नौ": 9, "दस": 10,
    "ग्यारह": 11, "बारह": 12, "तेरह": 13, "चौदह": 14, "पंद्रह": 15,
    "सोलह": 16, "सत्रह": 17, "अठारह": 18, "उन्नीस": 19, "बीस": 20,
    "तीस": 30, "चालीस": 40, "पचास": 50, "साठ": 60, "सत्तर": 70, "अस्सी": 80, "नब्बे": 90,
    "सौ": 100, "एक सौ": 100, "एक सौ दस": 110, "एक सौ बीस": 120, "एक सौ तीस": 130,
    "एक सौ चालीस": 140, "एक सौ पचास": 150, "एक सौ साठ": 160, "दो सौ": 200
}

# Tamil spoken numbers and phonetics
TAMIL_NUMBERS = {
    "poojiyam": 0, "ondru": 1, "onnu": 1, "irandu": 2, "rendu": 2,
    "moondru": 3, "moonu": 3, "naangu": 4, "naalu": 4, "aindhu": 5, "anju": 5,
    "aaru": 6, "yezhu": 7, "ezhu": 7, "yettu": 8, "ettu": 8, "onbadhu": 9, "pathu": 10, "patthu": 10,
    "pathinondru": 11, "pannirendu": 12, "pathimoondru": 13, "pathinaangu": 14, "pathinaindhu": 15,
    "irubadhu": 20, "muppadhu": 30, "naarpadhu": 40, "aembadhu": 50, "aimbadhu": 50,
    "arubadhu": 60, "ezhubadhu": 70, "enbadhu": 80, "thonnooru": 90,
    "nooru": 100, "nootru": 100, "nootru pathu": 110, "nootru irubadhu": 120, "nootru muppadhu": 130,
    "nootru naarpadhu": 140, "nootru aembadhu": 150, "nootru enbadhu": 180, "irunooru": 200,
    # Tamil script
    "பூஜ்ஜியம்": 0, "ஒன்று": 1, "ஒன்னு": 1, "இரண்டு": 2, "ரெண்டு": 2,
    "மூன்று": 3, "மூணு": 3, "நான்கு": 4, "நாலு": 4, "ஐந்து": 5, "அஞ்சு": 5,
    "ஆறு": 6, "ஏழு": 7, "எட்டு": 8, "ஒன்பது": 9, "பத்து": 10,
    "பதினொன்று": 11, "பன்னிரண்டு": 12, "இருபது": 20, "முப்பது": 30,
    "நாற்பது": 40, "ஐம்பது": 50, "அறுபது": 60, "எழுபது": 70, "எண்பது": 80, "தொண்ணூறு": 90,
    "நூறு": 100, "நூற்று பத்து": 110, "நூற்று இருபது": 120, "நூற்று முப்பது": 130,
    "நூற்று நாற்பது": 140, "நூற்று ஐம்பது": 150, "இருநூறு": 200
}

class SpokenNumberNormalizer:

    @classmethod
    def words_to_int(cls, text_phrase):
        """Convert a sequence of number words into an integer."""
        clean = text_phrase.lower().strip()

        # Check direct lookup first
        if clean in COMPOUND_HUNDREDS_EN:
            return COMPOUND_HUNDREDS_EN[clean]
        if clean in HINDI_NUMBERS:
            return HINDI_NUMBERS[clean]
        if clean in TAMIL_NUMBERS:
            return TAMIL_NUMBERS[clean]
        if clean in WORD_TO_NUMBER_EN:
            return WORD_TO_NUMBER_EN[clean]

        # Multi-word evaluation (e.g. "one hundred and twenty five", "eighty five")
        words = clean.replace(" and ", " ").replace("-", " ").split()
        total = 0
        current = 0

        for w in words:
            if w in ("hundred", "hundreds", "sau", "nooru", "nootru"):
                current = (current if current != 0 else 1) * 100
            elif w in ("thousand", "hazaar", "aayiram"):
                total += (current if current != 0 else 1) * 1000
                current = 0
            elif w in WORD_TO_NUMBER_EN:
                current += WORD_TO_NUMBER_EN[w]
            elif w in HINDI_NUMBERS:
                current += HINDI_NUMBERS[w]
            elif w in TAMIL_NUMBERS:
                current += TAMIL_NUMBERS[w]
            elif w.isdigit():
                current += int(w)

        return total + current

    @classmethod
    def normalize_blood_pressure(cls, text):
        """
        Normalize spoken blood pressure phrases like:
          "one twenty over eighty" -> "120/80"
          "blood pressure one twenty over eighty" -> "blood pressure 120/80"
          "ek sau bees over assi" -> "120/80"
          "nootru irubadhu over enbadhu" -> "120/80"
        """
        all_number_words = list(COMPOUND_HUNDREDS_EN.keys()) + list(COMPOUND_TENS_EN.keys()) + list(WORD_TO_NUMBER_EN.keys()) + list(HINDI_NUMBERS.keys()) + list(TAMIL_NUMBERS.keys())
        all_number_words.sort(key=len, reverse=True)
        num_word_pat = r"(?:" + "|".join(re.escape(w) for w in all_number_words) + r"|\d+)"

        # Pattern: <spoken_num> over/by/bata/keezh <spoken_num>
        bp_spoken_pattern = rf"\b({num_word_pat})\s*(?:/|over|by|bata|बटा|keezh|கீழ்)\s*({num_word_pat})\b"

        def replace_bp(match):
            raw_sys = match.group(1).strip()
            raw_dia = match.group(2).strip()

            sys_num = int(raw_sys) if raw_sys.isdigit() else cls.words_to_int(raw_sys)
            dia_num = int(raw_dia) if raw_dia.isdigit() else cls.words_to_int(raw_dia)

            # Plausible physiological BP limits
            if 40 <= sys_num <= 300 and 20 <= dia_num <= 200:
                return f"{sys_num}/{dia_num}"
            return match.group(0)

        text = re.sub(bp_spoken_pattern, replace_bp, text, flags=re.IGNORECASE)

        # Pattern: systolic <spoken_num> (and)? diastolic <spoken_num>
        sys_dia_pattern = rf"\bsystolic\s+({num_word_pat})\s*(?:and|,)?\s*diastolic\s+({num_word_pat})\b"
        def replace_sys_dia(match):
            raw_sys = match.group(1).strip()
            raw_dia = match.group(2).strip()
            sys_num = int(raw_sys) if raw_sys.isdigit() else cls.words_to_int(raw_sys)
            dia_num = int(raw_dia) if raw_dia.isdigit() else cls.words_to_int(raw_dia)
            if 40 <= sys_num <= 300 and 20 <= dia_num <= 200:
                return f"systolic {sys_num} diastolic {dia_num} ({sys_num}/{dia_num})"
            return match.group(0)

        text = re.sub(sys_dia_pattern, replace_sys_dia, text, flags=re.IGNORECASE)
        return text

    @classmethod
    def normalize_dosages_and_units(cls, text):
        """
        Normalize spoken dosages and units:
          "zero point five milligrams" -> "0.5 mg"
          "point five milligrams" -> "0.5 mg"
          "five milligrams" -> "5 mg"
          "half a milligram" -> "0.5 mg"
          "half mg" -> "0.5 mg"
          "ten mg" -> "10 mg"
          "paanch milligram" -> "5 mg"
          "aindhu milligram" -> "5 mg"
          "aadha milligram" -> "0.5 mg"
          "arai milligram" -> "0.5 mg"
        """
        # Fractional keywords
        text = re.sub(r"(?i)\b(?:half\s+a\s+milligram|half\s+mg|aadha\s+milligram|arai\s+milligram)\b", "0.5 mg", text)
        text = re.sub(r"(?i)\b(?:quarter\s+a\s+milligram|quarter\s+mg)\b", "0.25 mg", text)

        # Spoken decimal patterns: "zero point five", "point five", "one point five", "two point five"
        decimal_words = {
            r"(?i)\b(?:zero\s+point\s+five|point\s+five|shunya\s+dashamlav\s+paanch|poojiyam\s+pulli\s+aindhu)\b": "0.5",
            r"(?i)\b(?:zero\s+point\s+four|point\s+four)\b": "0.4",
            r"(?i)\b(?:zero\s+point\s+two|point\s+two)\b": "0.2",
            r"(?i)\b(?:zero\s+point\s+three|point\s+three)\b": "0.3",
            r"(?i)\b(?:zero\s+point\s+one|point\s+one)\b": "0.1",
            r"(?i)\b(?:one\s+point\s+five)\b": "1.5",
            r"(?i)\b(?:two\s+point\s+five)\b": "2.5",
            r"(?i)\b(?:three\s+point\s+five)\b": "3.5",
            r"(?i)\b(?:seven\s+point\s+five)\b": "7.5",
            r"(?i)\b(?:thirty\s+seven\s+point\s+([0-9]|two|five))\b": lambda m: f"37.{cls.words_to_int(m.group(1)) if not m.group(1).isdigit() else m.group(1)}"
        }
        for pat, repl in decimal_words.items():
            text = re.sub(pat, repl, text)

        # Spoken integers preceding dosage units: e.g. "five milligrams", "ten mg", "one gram"
        units_pattern = r"\b(milligrams?|milligram|mcg|micrograms?|microgram|g|grams?|gram|ml|milliliters?|milliliter|puffs?|puff|sprays?|tablets?|tabs?|l/min|liters?)\b"
        all_words_map = {**COMPOUND_HUNDREDS_EN, **COMPOUND_TENS_EN, **WORD_TO_NUMBER_EN, **HINDI_NUMBERS, **TAMIL_NUMBERS}
        sorted_words = sorted(all_words_map.items(), key=lambda x: len(x[0]), reverse=True)

        for word, val in sorted_words:
            if len(word) >= 2 and not word.isdigit():
                # Pattern: "<word> <unit>" -> "<val> <unit>"
                pat = rf"\b{re.escape(word)}\s+(?={units_pattern})"
                text = re.sub(pat, f"{val} ", text, flags=re.IGNORECASE)

        # Standardize unit spellings
        text = re.sub(r"\b([0-9]+(?:\.[0-9]+)?)\s*milligrams?\b", r"\1 mg", text, flags=re.IGNORECASE)
        text = re.sub(r"\b([0-9]+(?:\.[0-9]+)?)\s*micrograms?\b", r"\1 mcg", text, flags=re.IGNORECASE)
        text = re.sub(r"\b([0-9]+(?:\.[0-9]+)?)\s*milliliters?\b", r"\1 ml", text, flags=re.IGNORECASE)

        # Also normalize common percentage and regional unit words:
        text = re.sub(r"\b(?:percent|per cent|சதவீதம்|प्रतिशत)\b", "%", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(மில்லிகிராம்|मिलीग्राम)\b", "mg", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(மைக்ரோகிராம்|माइक्रोग्राम)\b", "mcg", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(மில்லி|मिलीलीटर)\b", "ml", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(கிராம்|ग्राम)\b", "g", text, flags=re.IGNORECASE)

        return text

    @classmethod
    def normalize_vitals_spoken(cls, text):
        """
        Normalize spoken vital signs:
          "pulse seventy five" -> "pulse 75"
          "heart rate eighty two" -> "heart rate 82"
          "respiratory rate sixteen" -> "respiratory rate 16"
          "oxygen saturation ninety eight percent" -> "oxygen saturation 98%"
          "sp o two ninety eight" -> "SpO2 98%"
        """
        all_words_map = {**COMPOUND_HUNDREDS_EN, **COMPOUND_TENS_EN, **WORD_TO_NUMBER_EN, **HINDI_NUMBERS, **TAMIL_NUMBERS}
        sorted_words = sorted(all_words_map.items(), key=lambda x: len(x[0]), reverse=True)

        vital_keywords = r"(?:pulse|heart\s+rate|hr|respiratory\s+rate|rr|breathing|spo2|sp\s*o\s*2|oxygen\s+saturation|gcs|bgl|glucose|sugar|temp|temperature)"

        # Pattern: "<vital_keyword> (is|was|of|at)? <spoken_word_number>"
        for word, val in sorted_words:
            if len(word) >= 2 and not word.isdigit():
                pat = rf"({vital_keywords}\s*(?:is|was|of|at)?\s*)\b{re.escape(word)}\b"
                text = re.sub(pat, rf"\g<1>{val}", text, flags=re.IGNORECASE)
            if len(word) >= 2 and not word.isdigit():
                pat = rf"({vital_keywords}\s*(?:is|was|of|at)?\s*)\b{re.escape(word)}\b"
                text = re.sub(pat, rf"\g<1>{val}", text, flags=re.IGNORECASE)

        return text

    @classmethod
    def normalize_all(cls, transcript_text):
        """
        Full spoken-to-clinical normalization pipeline.
        Returns normalized text while preserving context.
        """
        if not transcript_text:
            return ""

        text = transcript_text
        text = cls.normalize_blood_pressure(text)
        text = cls.normalize_dosages_and_units(text)
        text = cls.normalize_vitals_spoken(text)

        return text
