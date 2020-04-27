from utils import convert_euckp_to_unicode
from collections import Counter, defaultdict
import sqlite3
import os


def Byte4ToInt(arg1, arg2):
    return ((arg1[arg2 + 3] & 255) << 24) | ((arg1[arg2 + 2] & 255) << 16) | ((arg1[arg2 + 1] & 255) << 8) | (
                arg1[arg2] & 255)


def Byte2ToInt(arg1, arg2):
    return ((arg2 & 0xFF) << 8) | (arg1 & 0xFF)


class Dumper():

    def __init__(self, dicfile):
        self.dicfile = open(dicfile, 'rb')

    def dump_word_list_as_bytes(self, language_id = 0):
        wordlist = {}
        lang_index = {0: 0x4, 4: 0x10, 6: 0x24}
        if language_id not in lang_index:
            self.dicfile.close()
            raise ValueError("Invalid Language ID")

        self.dicfile.seek(lang_index[language_id])
        main_index = Byte4ToInt(self.dicfile.read(4), 0)
        self.dicfile.seek(main_index)
        max_size = Byte4ToInt(self.dicfile.read(4), 0) >> 2

        for i in range(max_size):
            self.dicfile.seek(i * 4 + main_index)
            cur_word_offset = Byte4ToInt(self.dicfile.read(4), 0)
            cur_word_address = main_index + cur_word_offset
            self.dicfile.seek(cur_word_address)
            word_length = int.from_bytes(self.dicfile.read(1), "little", signed=False)
            word, word_index = self.dicfile.read(word_length).split(b'\x00', 1)
            word_index = Byte4ToInt(word_index, 0)
            wordlist[word_index] = word

        return wordlist

    def dump_encoded_content(self):
        wordlist = []
        self.dicfile.seek(0)
        header_size = Byte4ToInt(self.dicfile.read(4), 0)
        self.dicfile.seek(header_size)
        index_size = Byte4ToInt(self.dicfile.read(4), 0)
        index_size_per_individual_language = index_size >> 2
        for i in range(index_size_per_individual_language):
            self.dicfile.seek(header_size + i * 4)
            current_word_address = Byte4ToInt(self.dicfile.read(4), 0)
            self.dicfile.seek(current_word_address + header_size)
            buffer_length = int.from_bytes(self.dicfile.read(2), "little", signed=False)
            encoded_content = self.dicfile.read(buffer_length)
            szEnglish, szChinese, szKorean, szField, _ = encoded_content.split(b'\x00')
            wordlist.append((szEnglish, szChinese, szKorean, szField))
        return wordlist

    def close(self):
        self.dicfile.close()


def create_substitution_dictionary(wordlist, content):
    res = defaultdict(list)
    for index, word in wordlist.items():
        if len(word) != len(content[index]):
            continue
        i = 0
        while i < len(word):
            if word[i] < 0x80:
                res[content[index][i]].append(word[i])
                i += 1
            else:
                res[content[index][i:i+2]].append(word[i:i+2])
                i += 2

    def most_common(lst):
        data = Counter(lst)
        return max(lst, key=data.get)

    return {key: most_common(value) for key, value in res.items()}


def translate_by_substitution(word, substitution_dictionary):
    i = 0
    res = bytearray(len(word))
    while i < len(word):
        try:
            if word[i:i+4] == b'\xd4\xe9\x83\xd4': # handling the case for 및 which was does not appear in the word list
                res[i:i+4] = b' \xB7\xF1 '
                i += 4
            elif word[i:i+2] == b'"$': # another special case unaccounted for...
                res[i:i+2] = b'TV'
                i +=2
            else:
                res[i:i + 2] = substitution_dictionary[word[i:i+2]]
                i += 2
        except KeyError as e:
            print("Error: Sequence %s not found in substitution dictionary." % word[i:i+2])
            res[i:i + 2] = b'??'
            i += 2
    return res


def create_keek_list_of_tuples(korean_wordlist, english_wordlist, field_content):

    def con(input):
        return convert_euckp_to_unicode(input).decode('utf-16')

    ek_data = []
    ke_data = []
    for index, element in korean_wordlist.items():
        if index in english_wordlist:
            str_kr_word = con(element)
            str_en_word = con(english_wordlist[index])
            ek_data.append((str_en_word, str_kr_word + ('\n\n(%s)' % field_content[index])))
            ke_data.append((str_kr_word, str_en_word + ('\n\n(%s)' % field_content[index])))
    return ke_data + ek_data

if __name__ == "__main__":

    d = Dumper("eckdata.dic")
    english_wordlist = d.dump_word_list_as_bytes(language_id=0)
    korean_wordlist = d.dump_word_list_as_bytes(language_id=6)
    full_content = d.dump_encoded_content()
    _, _, korean_content, field_content = zip(*full_content)

    subs = create_substitution_dictionary(korean_wordlist, korean_content)

    substituted_field_content = [translate_by_substitution(_, subs) for i, _ in enumerate(field_content)]
    decoded_field_content = [convert_euckp_to_unicode(_).decode('utf-16') for _ in substituted_field_content]

    final_data = create_keek_list_of_tuples(korean_wordlist,
                                            english_wordlist,
                                            decoded_field_content
    )
    final_data = sorted(final_data, key=lambda x: x[0])

    d.close()

    # Create database
    DB_NAME = "biyak.db"
    if os.path.exists(DB_NAME):
        os.remove(DB_NAME)
    conn = sqlite3.connect(DB_NAME)
    conn.execute("CREATE TABLE name (dicname text)")
    conn.execute("INSERT INTO name VALUES ('%s')" % "Biyak Technical Dictionary")
    conn.commit()
    conn.execute("CREATE TABLE dictionary (word text, definition text)")
    conn.executemany("INSERT INTO dictionary VALUES (?, ?)", final_data)
    conn.commit()
    conn.close()


