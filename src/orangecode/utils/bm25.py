"""轻量级、无外部依赖的 BM25 检索器，支持中英文混合分词。"""

import math
import re

# 匹配长度至少为 2 的字母数字串，或单个 CJK 中文表意字符
_TOKEN_RE = re.compile(r"[a-z0-9]{2,}|[\u4e00-\u9fff]")


def tokenize(text: str) -> list[str]:
    """对文本执行中英文混合分词。"""
    return _TOKEN_RE.findall(text.lower())


class BM25Okapi:
    """Okapi BM25 内存关键字检索模型。"""

    def __init__(
        self,
        corpus: list[str],
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        self.k1 = k1
        self.b = b
        self.corpus_size = len(corpus)
        tokenized_corpus = [tokenize(doc) for doc in corpus]
        self.doc_lens = [len(d) for d in tokenized_corpus]
        self.avgdl = sum(self.doc_lens) / self.corpus_size if self.corpus_size else 0.0

        self.doc_freqs: list[dict[str, int]] = []
        df: dict[str, int] = {}
        for doc in tokenized_corpus:
            freqs: dict[str, int] = {}
            for tok in doc:
                freqs[tok] = freqs.get(tok, 0) + 1
            self.doc_freqs.append(freqs)
            for tok in freqs:
                df[tok] = df.get(tok, 0) + 1

        n = self.corpus_size
        # 使用 Robertson-Spärck-Jones 公式并附带平滑保护项，防止 IDF 为负数
        self.idf = {
            term: math.log(1 + (n - count + 0.5) / (count + 0.5))
            for term, count in df.items()
        }

    def get_scores(self, query: str) -> list[float]:
        """计算给定 Query 对语料库中所有文档的相关度得分。"""
        query_tokens = tokenize(query)
        scores = [0.0] * self.corpus_size
        if not query_tokens or self.corpus_size == 0:
            return scores

        for term in query_tokens:
            idf = self.idf.get(term, 0.0)
            if idf <= 0.0:
                continue
            for i, freqs in enumerate(self.doc_freqs):
                f = freqs.get(term, 0)
                if f == 0:
                    continue
                dl = self.doc_lens[i]
                norm = self.k1 * (1 - self.b + self.b * dl / (self.avgdl or 1.0))
                scores[i] += idf * f * (self.k1 + 1) / (f + norm)
        return scores

    def search_top_k(self, query: str, k: int = 3) -> list[tuple[int, float]]:
        """返回得分最高的 Top-K 文档下标与分数。"""
        scores = self.get_scores(query)
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
        return [(idx, score) for idx, score in ranked[:k] if score > 0.0]
