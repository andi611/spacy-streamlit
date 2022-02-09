from dragonmapper import hanzi, transcriptions
import jieba
from jisho_api.word import Word
from jisho_api.sentence import Sentence
import pandas as pd
import re
import requests 
import spacy
from spacy_streamlit import visualize_ner, visualize_tokens
#from spacy.language import Language
from spacy.tokens import Doc
import spacy_ke
from spacy_wordnet.wordnet_annotator import WordnetAnnotator 
import streamlit as st
import nltk
from nltk.corpus import wordnet as wn

# Global variables
MODELS = {"中文": "zh_core_web_sm", 
          "English": "en_core_web_sm", 
          "日本語": "ja_ginza"}
models_to_display = list(MODELS.keys())
ZH_TEXT = """（中央社）迎接虎年到來，台北101今天表示，即日起推出「虎年新春燈光秀」，將持續至2月5日，每晚6時至10時，除整點會有報時燈光變化外，每15分鐘還會有3分鐘的燈光秀。台北101下午透過新聞稿表示，今年特別設計「虎年新春燈光秀」，從今晚開始閃耀台北天際線，一直延續至2月5日，共7天。"""
ZH_REGEX = "\d{2,4}[\u4E00-\u9FFF]+"
EN_TEXT = """(Reuters) Taiwan's government believes there is "enormous" room for cooperation with the European Union on semiconductors, responding to plans from the bloc to boost its chip industry and cut its dependence on U.S. and Asian supplies.
The EU's plan mentions Taiwan, home to the world's largest contract chipmaker TSMC and other leading semiconductor companies, as one of the "like-minded partners" Europe would like to work with.
The plan, unveiled on Tuesday, calls for the European Commission to ease funding rules for innovative semiconductor plants, a move that comes as a global chip shortage and supply chain bottlenecks have created havoc for many industries.
Taiwan's Foreign Ministry said in a statement it was pleased to see the strong momentum in bilateral trade and investment between Taiwan and the EU, and welcomed the EU attaching so much importance to the island.
"""
EN_REGEX = "(ed|ing)$"
JA_TEXT = """（朝日新聞）台湾気分のパワースポット ＪＲ大久保駅南口のすぐそばにある「東京媽祖廟（まそびょう）」は、台湾で広く信仰されている道教の神様を祭る。居酒屋やコンビニが並ぶ通りで、金色の竜など豪華な装飾が施された４階建ての赤い建物はとても目立つ。"""
JA_REGEX = "[たい]$"
DESCRIPTION = "AI模型輔助語言學習"
TOK_SEP = " | "

# External API callers
def moedict_caller(word):
    st.write(f"### {word}")
    req = requests.get(f"https://www.moedict.tw/a/{word}.json")
    if req:
        with st.expander("點擊 + 檢視結果"):
            st.json(req.json())
    else:
        st.write("查無結果")

def parse_jisho_senses(word):
    res = Word.request(word)
    response = res.dict()
    if response["meta"]["status"] == 200:
        data = response["data"]
        commons = [d for d in data if d["is_common"]]
        if commons:
            common = commons[0] # Only get the first entry that is common
            senses = common["senses"]
            if len(senses) > 3:
                senses = senses[:3]
            with st.container():
                for idx, sense in enumerate(senses):
                    eng_def = "; ".join(sense["english_definitions"])
                    pos = "/".join(sense["parts_of_speech"])
                    st.write(f"Sense {idx+1}: {eng_def} ({pos})")
        else:
            st.info("Found no common words on Jisho!")
    else:
        st.error("Can't get response from Jisho!")


def parse_jisho_sentences(word):
    res = Sentence.request(word)
    try:
        response = res.dict()
        data = response["data"]
        if len(data) > 3:
            sents = data[:3]
        else:
            sents = data
        with st.container():
            for idx, sent in enumerate(sents):
                eng = sent["en_translation"]
                jap = sent["japanese"]
                st.write(f"Sentence {idx+1}: {jap}")
                st.write(f"({eng})")
    except:
        st.info("Found no results on Jisho!")
            
# Custom tokenizer class
class JiebaTokenizer:
    def __init__(self, vocab):
        self.vocab = vocab

    def __call__(self, text):
        words = jieba.cut(text) # returns a generator
        tokens = list(words) # convert the genetator to a list
        spaces = [False] * len(tokens)
        doc = Doc(self.vocab, words=tokens, spaces=spaces)
        return doc
    
# Utility functions
def create_jap_df(tokens):
    seen_texts = []
    filtered_tokens = []
    for tok in tokens:
        if tok.text not in seen_texts:
            filtered_tokens.append(tok)
            
    df = pd.DataFrame(
      {
          "單詞": [tok.text for tok in filtered_tokens],
          "發音": ["/".join(tok.morph.get("Reading")) for tok in filtered_tokens],
          "詞形變化": ["/".join(tok.morph.get("Inflection")) for tok in filtered_tokens],
          "原形": [tok.lemma_ for tok in filtered_tokens],
          #"正規形": [tok.norm_ for tok in verbs],
      }
    )
    st.dataframe(df)
    csv = df.to_csv().encode('utf-8')
    st.download_button(
      label="下載表格",
      data=csv,
      file_name='jap_forms.csv',
      )

def create_eng_df(tokens):
    seen_texts = []
    filtered_tokens = []
    for tok in tokens:
        if tok.lemma_ not in seen_texts:
            filtered_tokens.append(tok)
            
    df = pd.DataFrame(
      {
          "單詞": [tok.text.lower() for tok in filtered_tokens],
          "詞類": [tok.pos_ for tok in filtered_tokens],
          "原形": [tok.lemma_ for tok in filtered_tokens],
      }
    )
    st.dataframe(df)
    csv = df.to_csv().encode('utf-8')
    st.download_button(
      label="下載表格",
      data=csv,
      file_name='eng_forms.csv',
      )
          
def filter_tokens(doc):
    clean_tokens = [tok for tok in doc if tok.pos_ not in ["PUNCT", "SYM"]]
    clean_tokens = [tok for tok in clean_tokens if not tok.like_email]
    clean_tokens = [tok for tok in clean_tokens if not tok.like_url]
    clean_tokens = [tok for tok in clean_tokens if not tok.like_num]
    clean_tokens = [tok for tok in clean_tokens if not tok.is_punct]
    clean_tokens = [tok for tok in clean_tokens if not tok.is_space]
    return clean_tokens

def get_def_and_ex_from_wordnet(word, pos_label):
    mapper = {
        "VERB": wn.VERB,
        "NOUN": wn.NOUN,
        "ADJ": wn.ADJ,
        "ADV": wn.ADV,
    }
    
    synsets = wn.synsets(word, pos=mapper[pos_label])
    if len(synsets) > 3:
        synsets = synsets[:3]
    
    sense_count = 1
    for syn in synsets:
        st.write(f"Relevant Sense {sense_count}: {syn.definition()}")
        sense_count += 1
        examples = syn.examples()
        if not examples:
            continue
        elif len(examples) > 3:
            examples = examples[:3]
        ex_count = 1
        for ex in examples:
            st.write(f"Relevant Example {ex_count} >>> {ex}")
            ex_count += 1    
        st.markdown("---")

def create_kw_section(doc):
    st.markdown("## 關鍵詞分析") 
    kw_num = st.slider("請選擇關鍵詞數量", 1, 10, 3)
    kws2scores = {keyword: score for keyword, score in doc._.extract_keywords(n=kw_num)}
    kws2scores = sorted(kws2scores.items(), key=lambda x: x[1], reverse=True)
    count = 1
    for keyword, score in kws2scores: 
        rounded_score = round(score, 3)
        st.write(f"{count} >>> {keyword} ({rounded_score})")
        count += 1 
            
# Page setting
st.set_page_config(
    page_icon="🤠",
    layout="wide",
    initial_sidebar_state="auto",
)

# Choose a language and select functions
st.markdown(f"# {DESCRIPTION}") 
st.sidebar.write("請選擇一種語言並勾選至少一個功能")
selected_model = st.sidebar.radio("", models_to_display)

# Load the selected model
nlp = spacy.load(MODELS[selected_model])
nlp.add_pipe("yake") # keyword extraction
          
# Merge entity spans to tokens
# nlp.add_pipe("merge_entities") 

# Download NLTK data 
nltk.download('wordnet')
nltk.download('omw') # standing for Open Multilingual WordNet

# Shared logic across languages
if selected_model == models_to_display[0]: # Chinese
    # Select a tokenizer if the Chinese model is chosen
    selected_tokenizer = st.radio("請選擇斷詞模型", ["jieba-TW", "spaCy"])
    if selected_tokenizer == "jieba-TW":
        nlp.tokenizer = JiebaTokenizer(nlp.vocab)
    default_text = ZH_TEXT
    default_regex = ZH_REGEX
elif selected_model == models_to_display[1]: # English
    default_text = EN_TEXT 
    default_regex = EN_REGEX 
elif selected_model == models_to_display[2]: # Japanese
    default_text = JA_TEXT
    default_regex = JA_REGEX 

st.markdown("## 待分析文本")     
st.info("請在下面的文字框輸入文本並按下Ctrl + Enter以更新分析結果")
text = st.text_area("",  default_text, height=200)
doc = nlp(text)
st.markdown("---")

# Language-specific logic 
punct_and_sym = ["PUNCT", "SYM"]
if selected_model == models_to_display[0]: # Chinese 
    #keywords_extraction = st.sidebar.checkbox("關鍵詞分析", False) # YAKE doesn't work for Chinese texts
    analyzed_text = st.sidebar.checkbox("分析後文本", True)
    defs_examples = st.sidebar.checkbox("單詞解釋與例句", True)
    #morphology = st.sidebar.checkbox("詞形變化", True)
    ner_viz = st.sidebar.checkbox("命名實體", True)
    tok_table = st.sidebar.checkbox("斷詞特徵", False)

    if analyzed_text:
        st.markdown("## 分析後文本") 
        for idx, sent in enumerate(doc.sents):
            tokens_text = [tok.text for tok in sent if tok.pos_ not in punct_and_sym]
            pinyins = [hanzi.to_pinyin(word) for word in tokens_text]
            display = []
            for text, pinyin in zip(tokens_text, pinyins):
                res = f"{text} [{pinyin}]"
                display.append(res)
            if display:
              display_text = TOK_SEP.join(display)
              st.write(f"{idx+1} >>> {display_text}")
            else:
              st.write(f"{idx+1} >>> EMPTY LINE")
    
    if defs_examples:
        st.markdown("## 單詞解釋與例句")
        clean_tokens = filter_tokens(doc)
        alphanum_pattern = re.compile(r"[a-zA-Z0-9]")
        clean_tokens_text = [tok.text for tok in clean_tokens if not alphanum_pattern.search(tok.text)]
        vocab = list(set(clean_tokens_text))
        if vocab:
            selected_words = st.multiselect("請選擇要查詢的單詞: ", vocab, vocab[0:3])
            for w in selected_words:
                moedict_caller(w)                        
    
    if ner_viz:
        ner_labels = nlp.get_pipe("ner").labels
        visualize_ner(doc, labels=ner_labels, show_table=False, title="命名實體")
        
    if tok_table:
        visualize_tokens(doc, attrs=["text", "pos_", "tag_", "dep_", "head"], title="斷詞特徵")
    
elif selected_model == models_to_display[2]: # Japanese 
    keywords_extraction = st.sidebar.checkbox("關鍵詞分析", False)
    analyzed_text = st.sidebar.checkbox("分析後文本", True)
    defs_examples = st.sidebar.checkbox("單詞解釋與例句", True)
    morphology = st.sidebar.checkbox("詞形變化", False)
    ner_viz = st.sidebar.checkbox("命名實體", True)
    tok_table = st.sidebar.checkbox("斷詞特徵", False)
    
    if keywords_extraction:
        create_kw_section(doc)

    if analyzed_text:
        st.markdown("## 分析後文本") 
        for idx, sent in enumerate(doc.sents):
            clean_tokens = [tok for tok in sent if tok.pos_ not in ["PUNCT", "SYM"]]
            tokens_text = [tok.text for tok in clean_tokens]
            readings = ["/".join(tok.morph.get("Reading")) for tok in clean_tokens]
            display = [f"{text} [{reading}]" for text, reading in zip(tokens_text, readings)]
            if display:
              display_text = TOK_SEP.join(display)
              st.write(f"{idx+1} >>> {display_text}")
            else:
              st.write(f"{idx+1} >>> EMPTY LINE")  
    
    if defs_examples:
        st.markdown("## 單詞解釋與例句")
        clean_tokens = filter_tokens(doc)
        alphanum_pattern = re.compile(r"[a-zA-Z0-9]")
        clean_lemmas = [tok.lemma_ for tok in clean_tokens if not alphanum_pattern.search(tok.lemma_)]
        vocab = list(set(clean_lemmas))
        if vocab:
            selected_words = st.multiselect("請選擇要查詢的單詞: ", vocab, vocab[0:3])
            for w in selected_words:
                st.write(f"### {w}")
                with st.expander("點擊 + 檢視結果"):
                    parse_jisho_senses(w)
                    parse_jisho_sentences(w)
    
    if morphology:
        st.markdown("## 詞形變化")
        # Collect inflected forms
        inflected_forms = [tok for tok in doc if tok.tag_.startswith("動詞") or tok.tag_.startswith("形")]
        if inflected_forms:
            create_jap_df(inflected_forms)

    if ner_viz:
        ner_labels = nlp.get_pipe("ner").labels
        visualize_ner(doc, labels=ner_labels, show_table=False, title="命名實體")
        
    if tok_table:
        visualize_tokens(doc, attrs=["text", "pos_", "tag_", "dep_", "head"], title="斷詞特徵")
        
elif selected_model == models_to_display[1]: # English 
    keywords_extraction = st.sidebar.checkbox("關鍵詞分析", False)
    analyzed_text = st.sidebar.checkbox("分析後文本", True)
    defs_examples = st.sidebar.checkbox("單詞解釋與例句", True)
    morphology = st.sidebar.checkbox("詞形變化", False)
    ner_viz = st.sidebar.checkbox("命名實體", True)
    tok_table = st.sidebar.checkbox("斷詞特徵", False)
    
    if keywords_extraction:
        create_kw_section(doc)
    
    if analyzed_text:
        st.markdown("## 分析後文本") 
        nlp.add_pipe("spacy_wordnet", after='tagger', config={'lang': nlp.lang})
        doc = nlp(text)
        for idx, sent in enumerate(doc.sents):
            enriched_sentence = []
            for tok in sent:
                if tok.pos_ != "VERB":
                    enriched_sentence.append(tok.text)
                else:
                    synsets = tok._.wordnet.synsets()
                    if synsets:
                        v_synsets = [s for s in synsets if s.pos()=='v']
                        if not v_synsets:
                            enriched_sentence.append(tok.text)
                        else:
                            lemmas_for_synset = [lemma for s in v_synsets for lemma in s.lemma_names()]
                            lemmas_for_synset = list(set(lemmas_for_synset))

                            try:
                                lemmas_for_synset.remove(tok.text)
                            except:
                                pass

                            if len(lemmas_for_synset) > 5:
                                lemmas_for_synset = lemmas_for_synset[:5]

                            lemmas_for_synset = [s.replace("_", " ") for s in lemmas_for_synset]
                            lemmas_for_synset = " | ".join(lemmas_for_synset)
                            enriched_tok = f"{tok.text} (cf. {lemmas_for_synset})"
                            enriched_sentence.append(enriched_tok)  


            display_text = " ".join(enriched_sentence)
            st.write(f"{idx+1} >>> {display_text}")     

    if defs_examples:
        st.markdown("## 單詞解釋與例句")
        clean_tokens = filter_tokens(doc)
        num_pattern = re.compile(r"[0-9]")
        clean_tokens = [tok for tok in clean_tokens if not num_pattern.search(tok.lemma_)]
        selected_pos = ["VERB", "NOUN", "ADJ", "ADV"]
        clean_tokens = [tok for tok in clean_tokens if tok.pos_ in selected_pos]
        tokens_lemma_pos = [tok.lemma_ + " | " + tok.pos_ for tok in clean_tokens]
        vocab = list(set(tokens_lemma_pos))
        if vocab:
            selected_words = st.multiselect("請選擇要查詢的單詞: ", vocab, vocab[0:3])
            for w in selected_words:
                word_pos = w.split("|")
                word = word_pos[0].strip()
                pos = word_pos[1].strip()
                st.write(f"### {w}")
                with st.expander("點擊 + 檢視結果"):
                    get_def_and_ex_from_wordnet(word, pos)

    if morphology:
        st.markdown("## 詞形變化")
        # Collect inflected forms
        inflected_forms = [tok for tok in doc if tok.text.lower() != tok.lemma_.lower()]
        if inflected_forms:
            create_eng_df(inflected_forms)

    if ner_viz:
        ner_labels = nlp.get_pipe("ner").labels
        visualize_ner(doc, labels=ner_labels, show_table=False, title="命名實體")
        
    if tok_table:
        visualize_tokens(doc, attrs=["text", "pos_", "tag_", "dep_", "head"], title="斷詞特徵")
