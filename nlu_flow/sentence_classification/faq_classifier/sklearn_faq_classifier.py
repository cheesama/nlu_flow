from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report
from sklearn.pipeline import make_pipeline
from sklearn.feature_extraction.text import CountVectorizer, TfidfTransformer
from sklearn.svm import SVC
from sklearn.ensemble import RandomForestClassifier, AdaBoostClassifier

from tqdm import tqdm
from pprint import pprint

from nlu_flow.utils import meta_db_client
from nlu_flow.preprocessor.text_preprocessor import normalize

import os, sys
import dill
import random

def train_faq_classifier():
    # load dataset
    utterances = []
    labels = []

    ## get synonym data for data augmentation(for FAQ data augmentation)
    synonyms = []
    synonym_data = meta_db_client.get("meta-entities")
    for data in tqdm(
        synonym_data, desc=f"collecting synonym data for data augmentation ..."
    ):
        if type(data) != dict:
            print(f"check data type : {data}")
            continue

        synonyms += [
            normalize(each_synonym.get("synonym"))
            for each_synonym in data.get("meta_synonyms")
        ] + [normalize(data.get("Entity_Value"))]

    faq_data = meta_db_client.get("nlu-faq-questions")
    for data in tqdm(faq_data, desc=f"collecting faq data ... "):
        target_utterance = normalize(data["question"])

        # check synonym is included
        for synonym_list in random.choices(synonyms, k=10):
            for i, prev_value in enumerate(synonym_list):
                if prev_value in target_utterance:
                    for j, post_value in enumerate(synonym_list):
                        if i == j:
                            continue
                        utterances.append(target_utterance.replace(prev_value, post_value))
                        labels.append(data["faq_intent"])
                    break

        utterances.append(normalize(data["question"], with_space=True))
        labels.append(data["faq_intent"])

    print (f'dataset num: {len(utterances)}')

    X_train, X_test, y_train, y_test = train_test_split(
        utterances, labels, random_state=88
    )

    svc = make_pipeline(CountVectorizer(analyzer="char_wb"), SVC(probability=True))
    print("faq classifier training(with SVC)")
    svc.fit(X_train, y_train)
    print("model training done, validation reporting")
    y_pred = svc.predict(X_test)
    print(classification_report(y_test, y_pred))

    with open("report.md", "w") as reportFile:
        print("faq classification result", file=reportFile)
        print(classification_report(y_test, y_pred), file=reportFile)

    # save faq classifier model
    with open("faq_classifier_model.svc", "wb") as f:
        dill.dump(svc, f)
        print("faq_classifier model saved : faq_classifier_model.svc")


train_faq_classifier()
