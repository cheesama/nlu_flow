from Korpora import Korpora, KoreanChatbotKorpus
from tqdm import tqdm

from embedding_transformer import EmbeddingTransformer

from nlu_flow.preprocessor.text_preprocessor import normalize
from nlu_flow.utils.kor_char_tokenizer import KorCharTokenizer
from nlu_flow.utils import meta_db_client

from torch.nn import functional as F
from torch.utils.data import DataLoader
from torch.optim import Adam, lr_scheduler
from torch.utils.tensorboard import SummaryWriter
import torch
import torch.nn as nn

import os, sys
import multiprocessing
import argparse
import random

# downlad dataset
chatbot_corpus = KoreanChatbotKorpus()

tokenizer = KorCharTokenizer()

# prepare torch dataset
class ChatbotKorpusDataset(torch.utils.data.Dataset):
    def __init__(self, questions, answers, tokenizer, padding=True):
        assert len(questions) == len(answers)

        self.tokenizer = tokenizer
        self.dataset = []
        self.padding = padding

        for i, question in tqdm(enumerate(questions), desc="preparing data ..."):
            question_tokens = self.tokenizer.tokenize(questions[i], padding=False)
            answer_tokens = self.tokenizer.tokenize(answers[i], padding=False)
            #print (f'question_tokens : {len(question_tokens)}')
            #print (f'answer_tokens : {len(answer_tokens)}')
            entire_tokens = question_tokens + answer_tokens[1:] # except asnwer tokens BOS token
            #print (f'entire_tokens : {len(entire_tokens)}')
            if self.padding:
                if len(entire_tokens) < self.tokenizer.max_len + 1:
                    entire_tokens += [self.tokenizer.get_pad_token_id()] * (
                        self.tokenizer.max_len - len(entire_tokens) + 1
                    )

                self.dataset.append(
                    (entire_tokens[: self.tokenizer.max_len], entire_tokens[1:])
                )
            else:
                entire_tokens = entire_tokens[:self.tokenizer.max_len]
                self.dataset.append((entire_tokens[:-1], entire_tokens[1:]))

    def __len__(self):
        return len(self.dataset)

    def __getitem__(self, idx):
        return self.dataset[idx][0], self.dataset[idx][1]


questions = []
answers = []

# korpora dataset add
for qa in chatbot_corpus.train:
    questions.append(qa.text)
    answers.append(qa.pair)

# meta db dataset add
chitchat_class_dict = dict()

meta_responses = meta_db_client.get('nlu-chitchat-responses')
for response in tqdm(meta_responses, desc='meta db chitchat questions & response organizing ...'):
    if response['class_name'] is None:
        continue

    if response['class_name']['classes'] not in chitchat_class_dict:
        chitchat_class_dict[response['class_name']['classes']] = []
    chitchat_class_dict[response['class_name']['classes']].append(response['response'])

meta_questions = meta_db_client.get('nlu-chitchat-utterances')
for question in tqdm(meta_questions, desc='meta db chitchat dataset adding ...'):
    if question['class_name'] is None:
        continue

    questions.append(question['utterance'])
    answers.append(random.choice(chitchat_class_dict[question['class_name']['classes']]))

train_dataset = ChatbotKorpusDataset(questions, answers, tokenizer, padding=False)

def sequence_collate_fn(batch):
    min_token_length = tokenizer.max_len

    for i in range(len(batch)):
        min_token_length = min(min_token_length, len(batch[i][0]))

    question_tensor = torch.LongTensor([q_tokens[:min_token_length] for q_tokens, a_tokens in batch])
    answer_tensor = torch.LongTensor([a_tokens[:min_token_length] for q_tokens, a_tokens in batch])

    #print (f'q: {question_tensor}')
    #print (f'a: {answer_tensor}')

    return question_tensor, answer_tensor

def train_model(n_epochs=20, lr=0.0001):
    batch_size = tokenizer.max_len

    train_loader = DataLoader(
        train_dataset,
        batch_size=batch_size,
        num_workers=multiprocessing.cpu_count(),
        drop_last=True,
        collate_fn=sequence_collate_fn,
    )

    # model definition
    model = EmbeddingTransformer(
        vocab_size=tokenizer.get_vocab_size(),
        max_seq_len=tokenizer.get_seq_len(),
        pad_token_id=tokenizer.get_pad_token_id(),
    )

    if torch.cuda.is_available():
        model = model.cuda()

    # train model
    optimizer = Adam(model.parameters(), lr=float(lr))
    scheduler = lr_scheduler.StepLR(optimizer, 1.0, gamma=0.95)
    loss_fn = nn.CrossEntropyLoss(ignore_index=tokenizer.get_pad_token_id())

    writer = SummaryWriter(log_dir=f"runs/epochs:{n_epochs}_lr:{lr}")
    global_step = 0

    for epoch in range(1, int(n_epochs) + 1):
        model.train()

        progress = tqdm(enumerate(train_loader), leave=False)
        for batch_idx, (question, answer) in progress:
            if torch.cuda.is_available():
                question = question.cuda()
                answer = answer.cuda()

            optimizer.zero_grad()
            pred = model(question)

            loss = loss_fn(pred.transpose(1, 2), answer)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 0.5)
            optimizer.step()

            progress.set_description(
                f"training model, epoch:{epoch}, iter: {global_step}, loss:{loss.cpu().item()}"
            )
            writer.add_scalar("Loss/train", loss.cpu().item(), global_step)
            global_step += 1

        torch.save(model.state_dict(), "transformer_chitchat_response_model.modeldict")
        scheduler.step()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--n_epochs", default=30)
    parser.add_argument("--lr", default=0.0001)
    args = parser.parse_args()

    train_model(int(args.n_epochs), float(args.lr))
