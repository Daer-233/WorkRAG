"""Small corpus BM25 with positive Robertson IDF and deterministic tokenization."""
from collections import Counter
import math
import re


def tokenize(text):
    text=text.casefold()
    terms=re.findall(r'[a-z0-9][a-z0-9._+:/-]*',text)
    for segment in re.findall(r'[\u4e00-\u9fff]+',text):
        terms.extend(segment[i:i+2] for i in range(len(segment)-1))
        if len(segment)==1: terms.append(segment)
    return terms


class BM25:
    def __init__(self, examples, k1=1.5, b=.75):
        self.examples=examples;self.k1=k1;self.b=b
        self.terms=[Counter(tokenize(row['text'])) for row in examples]
        self.lengths=[sum(row.values()) for row in self.terms]
        self.average=sum(self.lengths)/max(1,len(examples)) or 1
        frequency=Counter(term for row in self.terms for term in row)
        self.idf={term:math.log1p((len(examples)-count+.5)/(count+.5)) for term,count in frequency.items()}

    def scores(self, question):
        query=set(tokenize(question));scores={}
        for sample,terms,length in zip(self.examples,self.terms,self.lengths):
            score=0.
            for term in query:
                tf=terms.get(term,0)
                if tf:
                    score+=self.idf[term]*(tf*(self.k1+1))/(tf+self.k1*(1-self.b+self.b*length/self.average))
            label=sample['intent']
            scores[label]=max(scores.get(label,0.),score)
        return scores


def ranking(scores):
    ordered=sorted(scores,key=lambda label:(-scores[label],label))
    if not ordered: return None,0.,0.
    best=ordered[0];score=scores[best]
    return best,score,score-(scores[ordered[1]] if len(ordered)>1 else 0.)


def accepted(scores, thresholds):
    label,score,margin=ranking(scores)
    gate=thresholds.get(label)
    return bool(gate and score>0 and score>=gate['score'] and margin>=gate['margin'])
