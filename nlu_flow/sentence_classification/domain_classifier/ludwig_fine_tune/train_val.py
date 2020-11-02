from nlu_flow.utils import meta_db_client
from tqdm import tqdm

import dill
import os, sys
import random
import json

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

    synonyms.append([each_synonym.get("synonym") for each_synonym in data.get("meta_synonyms")] + [data.get("Entity_Value")])

total_scenario_utter_num  = 0
total_OOD_utter_num = 0

## faq domain
faq_data = meta_db_client.get("nlu-faq-questions")
for data in tqdm(faq_data, desc=f"collecting faq data ... "):
    if data["faq_intent"] is None or len(data["faq_intent"]) < 2:
        print(f"check data! : {data}")
        continue

    target_utterance = data["question"]

    # check synonym is included
    for synonym_list in synonyms:
        for i, prev_value in enumerate(synonym_list):
            if prev_value in target_utterance:
                for j, post_value in enumerate(synonym_list):
                    if i == j:
                        continue
                    utterances.append(target_utterance.replace(prev_value, post_value))
                    labels.append("faq")

## scenario domain
scenario_data = meta_db_client.get("nlu-intent-entity-utterances")
for data in tqdm(scenario_data, desc=f"collecting table data : nlu-intent-entity-utterances"):
    if type(data) != dict:
        print(f"check data type : {data}")
        continue

    total_scenario_utter_num += 1

    if "faq" in data["intent_id"]["Intent_ID"].lower():
        utterances.append(data["utterance"])
        labels.append("faq")
    elif data["intent_id"]["Intent_ID"] == "intent_OOD":
        utterances.append(data["utterance"])
        labels.append("out_of_domain")
        total_OOD_utter_num += 1
    else:
        utterances.append(data["utterance"])
        labels.append("scenario")

## out of domain
slang_training_data = meta_db_client.get("nlu-slang-trainings", max_num=total_scenario_utter_num)
for i, data in tqdm(enumerate(slang_training_data), desc=f"collecting table data : nlu-slang-trainings ...",):
    if i > total_scenario_utter_num:
        break

    if type(data) != dict:
        print (f'check data type: {data}')
        continue

    utterances.append(data["utterance"])
    labels.append("out_of_domain")
    total_OOD_utter_num += 1

chitchat_data = meta_db_client.get("nlu-chitchat-utterances")
for data in tqdm(chitchat_data, desc=f"collecting table data : nlu-chitchat-utterances"):
    utterances.append(data["utterance"])
    labels.append("out_of_domain")
    total_OOD_utter_num += 1

with open('domain_dataset.tsv', 'w') as domainData:
    domainData.write('text\tclass\n')
    
    for i, utter in enumerate(utterances):
        domainData.write(utter.strip().replace('\t',' '))
        domainData.write('\t')
        domainData.write(labels[i].strip().replace('\t', ' '))
        domainData.write('\n')

os.system('rm -rf results')
os.system('ludwig experiment --dataset domain_dataset.tsv --config_file config.yml')

#write result to file
with open('results/experiment_run/test_statistics.json') as f:
    test_result = json.load(f)

    with open('report.md', 'w') as reportFile:
        reportFile.write('faq classification test result\n')
        json.dump(test_result['class']['overall_stats'], reportFile, indent=4)