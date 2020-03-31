import argparse
import json
import csv
import itertools
import random
import nltk
from nltk.tokenize import word_tokenize
from collections import defaultdict, Counter
import numpy as np
import pickle
import torch
import torch.nn as nn

import fasttext

from source.utils import get_art_id_from_dpg_history, build_vocab_from_word_counts, pad_sequence, reverse_mapping_dict
from sklearn.model_selection import train_test_split



DATA_TYPES = ["NPA", "DPG", "Adressa"]

FILE_NAMES_NPA = {"click": "ClickData_sample.tsv", "news": "DocMeta_sample.tsv"}


def sample_n_from_elements(elements, ratio):
    '''

    :param elements: collection of elements from which to sample, e.g. article id for neg impressions
    :param ratio: total number of samples to be returned
    :return: random sample of size 'ratio' from the given collection 'nnn'
    '''
    if ratio > len(elements):
        return random.sample(elements * (ratio // len(elements) + 1), ratio) # expand sequence with duplicates so that we can sample enough elems
    else:
        return random.sample(elements, ratio)


def determine_pos_cands(impres, n_min, n_max, neg_sample_ratio, scale=8):

    #determine number of candidates depending on the number of positive impressions
    n_cands = min(n_max, np.log(len(impres)) * scale // (neg_sample_ratio + 1))

    if n_cands > len(impres) // 2:
        n_cands = n_min

    pos_cands = [impres.pop()]
    pos_cands += random.sample(impres, n_cands-1)

    return pos_cands


def create_train_sample(pos_sample, cand_article_ids, art_id2idx, neg_sample_ratio, candidate_generation='neg_sampling', preserve_seq_order=False):
    sample = ()

    if candidate_generation == 'neg_sampling':
        candidate_articles = [art_id2idx[art_id] for art_id in sample_n_from_elements(cand_article_ids, neg_sample_ratio)]
        candidate_articles.append(pos_sample)
        lbls = [0] * neg_sample_ratio + [1]  # create temp labels
        candidate_articles = list(zip(candidate_articles, lbls))  # zip art_id and label
        random.shuffle(candidate_articles)  # shuffle article ids with corresponding label
        candidate_articles = np.array(candidate_articles)
    else:
        raise NotImplementedError()

    # if preserve_seq_order:
    #     raise NotImplementedError()
    # else:
    #     pos_set = list(set(pos_impre) - set([pos_sample]))  # remove positive sample from user history
    #     # sample RANDOM elems from set of pos impressions -> Note that this is the orig. NPA approach => Sequence Order is lost
    #     hist = [int(p) for p in random.sample(pos_set, min(max_hist_len, len(pos_set)))[:max_hist_len]]
    #
    # hist += [0] * (max_hist_len - len(hist))
    #
    # # add training instance
    # # add_instance_to_data()
    # candidates['train'].append(candidate_articles[:, 0])  # ids of candidate items
    # lbls = candidate_articles[:, 1]
    # assert lbls.__contains__(1)  # sanity check
    # labels['train'].append(lbls)
    #
    # user_ids['train'].append(u_id2idx[u_id])
    # user_hist_pos['train'].append(hist)
    #
    # data_train_prepped.append(
    #     (u_id2idx[u_id],
    #      hist,
    #      candidate_articles[:, 0],
    #      candidate_articles[:, 0])
    # )



    pass


def prep_dpg_user_file_wu(user_file, news_file, art_id2idx, test_interval_days : int, neg_sample_ratio=4, max_hist_len=50, preserve_seq=False):
    '''
    Given a subsample of users and the valid articles, we truncate and encode users' reading history with article indices.
    Construct the data input for the Wu NPA as follows:
     'input': (u_id, history, candidates), 'labels': lbls

    Apply negative sampling to produce 'candidate' list of positive and negative elements

    :param user_file: (str) path pointing to pickled subsample of user data
    :param article_ids: set containing all valid article ids
    :param art_id2idx: (dict) mapping from article id to index
    :param neg_sample_ratio: int ratio for number of negative samples
    :param max_hist_len: (int) maximum length of a user's history, for truncating
    :param test_interval: (int) number of days specifying the time interval for the testing set
    :return:
    '''
    with open(user_file, "rb") as fin:
        user_data = pickle.load(fin)

    with open(news_file, "rb") as fin:
        news_data = pickle.load(fin)

    log_file = "/".join(user_file.split("/")[:-1]) + '/logging_dates.json'
    with open(log_file, 'r') as fin:
        logging_dates = json.load(fin)

    # determine start of the test interval in UNIX time
    if "threshold" in logging_dates.keys():
        start_test_interval = logging_dates['threshold']
    else:
        start_test_interval = logging_dates['last'] - ((60*60*24) * test_interval_days)

    u_id2idx = {}

    user_ids = {'train': [], 'test': []}
    candidates = {'train': [], 'test': []}
    labels = {'train': [], 'test': []}
    user_hist_pos = {'train': [], 'test': []}

    data_train_prepped = []
    data_test_prepped = []

    '''
    - For each user, we produce N training samples (N := # pos impressions) => all users have at least 5 articles
    - test samples is constrained by time (last week)
    - 
    4) Keep it simple for reproduction: 
        - for training, use the first M impressions up to test date threshold
        - for testing, use impressions counting backwards from last entry
        - if user has no impressions during testing interval, keep only for training 
    
    Notes from Wu: 
    - testing: for each user, subsample a user history (same for all test candidates)
    - take each positive impression from the test week and create a test instance with history and user_id
    - take each 'neg' impression as well
    - during inference, the forward pass processes 1 candidate at a time
    - the evaluation metrics are computed per user with the individual results for each testing instances following a session-index
    
    '''

    if len(news_data) > 1:
        articles_train = news_data['train'] # articles appearing in the training interval
        articles_test = news_data['test'] # collect all articles appearing in the test interval
    else:
        articles_train = set()
        articles_test = set()

    for u_id in user_data.keys():

        u_id2idx[u_id] = len(u_id2idx) # create mapping from u_id to index

        # aggregate article ids from user data
        # divide into training & test samples
        # constraint train set by time

        w_time_stamp = False
        pos_impre, time_stamps = zip(*[(art_id2idx[art_id], time_stamp)
                                       for _, art_id, time_stamp in user_data[u_id]["articles_read"]])

        if "articles_train" in user_data[u_id].keys():
            #[f(x) if condition else g(x) for x in sequence]
            train_impres = [(art_id2idx[art_id], time_stamp) if w_time_stamp else art_id2idx[art_id]
                            for _, art_id, time_stamp in user_data[u_id]['articles_train']] # (id, time)
            test_impres = [(art_id2idx[art_id], time_stamp) if w_time_stamp else art_id2idx[art_id]
                            for _, art_id, time_stamp in user_data[u_id]['articles_test']]
        else:
            train_impres, test_impres = [], []

            for impression, time_stamp in zip(pos_impre, time_stamps):
                if time_stamp < start_test_interval:
                    train_impres.append((impression, time_stamp) if w_time_stamp else impression)
                else:
                    test_impres.append((impression, time_stamp) if w_time_stamp else impression)

        # assumption: for testing use the entire reading history of that user but evaluate on unseen articles

        cand_article_ids = articles_train - set(train_impres)  # exclude positive samples from pool of pot. neg. samples
        for pos_sample in train_impres:
            #
            # (u_id, hist, cands, lbls)
            #train_sample = create_train_sample(pos_sample, cand_article_ids, neg_sample_ratio, candidate_generation='neg_sampling')
            #
            # Candidate Generation: generate negative samples
            candidate_articles = [art_id2idx[art_id] for art_id in sample_n_from_elements(cand_article_ids, neg_sample_ratio)]
            candidate_articles.append(pos_sample)
            lbls = [0] * neg_sample_ratio + [1] # create temp labels
            candidate_articles = list(zip(candidate_articles, lbls)) # zip art_id and label
            random.shuffle(candidate_articles) # shuffle article ids with corresponding label
            candidate_articles = np.array(candidate_articles)

            if preserve_seq:
                pass
            else:
                pos_set = list(set(pos_impre) - set([pos_sample]))  # remove positive sample from user history
                # sample RANDOM elems from set of pos impressions -> Note that this is the orig. NPA approach => Sequence Order is lost
                hist = [int(p) for p in random.sample(pos_set, min(max_hist_len, len(pos_set)))[:max_hist_len]]

            hist += [0] * (max_hist_len - len(hist))

            # add training instance
            #add_instance_to_data()
            candidates['train'].append(candidate_articles[:, 0])  # ids of candidate items
            lbls = candidate_articles[:, 1]
            assert lbls.__contains__(1) # sanity check
            labels['train'].append(lbls)

            user_ids['train'].append(u_id2idx[u_id])
            user_hist_pos['train'].append(hist)

            data_train_prepped.append(
                (u_id2idx[u_id],
                hist,
                candidate_articles[:, 0],
                candidate_articles[:, 1])
            )

        # create test instances
        if len(test_impres) != 0:
            # subsample history: RANDOM elems from set of pos impressions
            pos_set = pos_impre
            hist_test = [int(p) for p in random.sample(pos_set, min(max_hist_len, len(pos_set)))[:max_hist_len]]
            hist_test += [0] * (max_hist_len - len(hist_test))

            if w_time_stamp:
                test_ids = set(list(zip(*test_impres))[0])
            else:
                test_ids = set(test_impres)

            cand_article_ids = articles_test - test_ids

            for pos_test_sample in test_impres:
                '''              
                - Remove pos impressions from pool of cand articles
                - Sample negative examples
                - Add labels
                - Shuffle zip(cands, lbls)            
                - add samples to data dict            
                '''

                #generate test candidates
                ## sample candidates from articles in test interval
                candidate_articles = [art_id2idx[art_id] for art_id in
                                      sample_n_from_elements(cand_article_ids, neg_sample_ratio)]
                candidate_articles.append(pos_test_sample)
                lbls = [0] * neg_sample_ratio + [1]  # create temp labels
                candidate_articles = list(zip(candidate_articles, lbls))  # zip art_id and label
                #random.shuffle(candidate_articles)  # shuffle article ids with corresponding label
                candidate_articles = np.array(candidate_articles)

                # add test instance to data
                candidates['test'].append(candidate_articles[:, 0]) # K+1 candidates
                labels['test'].append(candidate_articles[:, 1])

                user_ids['test'].append(u_id2idx[u_id])
                user_hist_pos['test'].append(hist_test)

    #
    #reformat to np int arrays
    candidates['train'] = np.array(candidates['train'], dtype='int32')
    labels['train'] = np.array(labels['train'], dtype='int32')
    user_ids['train'] = np.array(user_ids['train'], dtype='int32')
    user_hist_pos['train'] = np.array(user_hist_pos['train'], dtype='int32')

    candidates['test'] = np.array(candidates['test'], dtype='int32')
    labels['test'] = np.array(labels['test'], dtype='int32')
    user_ids['test'] = np.array(user_ids['test'], dtype='int32')
    user_hist_pos['test'] = np.array(user_hist_pos['test'], dtype='int32')

    data = {}
    data['train'] = [{'input': (u_id, hist, cands), 'labels': np.array(lbls)} for u_id, hist, cands, lbls
                    in zip(user_ids['train'], user_hist_pos['train'], candidates['train'], labels['train'])]

    data['test'] = [{'input': (u_id, hist, cands), 'labels': np.array(lbls)} for u_id, hist, cands, lbls
                    in zip(user_ids['test'], user_hist_pos['test'], candidates['test'], labels['test'])]

    print("Train samples: {} \t Test: {}".format(len(data['train']), len(data['test'])))

    return u_id2idx, data

def preprocess_dpg_news_file(news_file, tokenizer, min_counts_for_vocab=2, max_article_len=30, max_vocab_size=30000):

    with open(news_file, 'rb') as f:
        news_data = pickle.load(f)

    article_data = news_data['all']

    vocab = defaultdict(int)
    news_as_word_ids = []
    art_id2idx = {}

    # 1. construct raw vocab
    print("construct raw vocabulary ...")
    vocab_raw = Counter({'PAD': 999999})

    for art_id in article_data:
        tokens = tokenizer(article_data[art_id]["snippet"].lower(), language='dutch')
        vocab_raw.update(tokens)
        article_data[art_id]['tokens'] = tokens

        if len(vocab_raw) % 1e4 == 0:
            print(len(vocab_raw))

    # 2. construct working vocab
    print("construct working vocabulary ...")
    vocab = build_vocab_from_word_counts(vocab_raw, max_vocab_size, min_counts_for_vocab)
    print("Vocab: {}  Raw: {}".format(len(vocab), len(vocab_raw)))
    #del(vocab_raw)

    # 3. encode news as sequence of word_ids
    print("encode news as word_ids ...")
    news_as_word_ids = [[0] * max_article_len]  # encoded news title
    art_id2idx = {'0': 0}  # dictionary news indices

    for art_id in article_data:
        word_ids = []

        art_id2idx[art_id] = len(art_id2idx) # map article id to index

        # get word_ids from news title
        for word in article_data[art_id]['tokens']:
            # if word occurs in vocabulary, add the id
            # unknown words are omitted
            if word in vocab:
                word_ids.append(vocab[word])

        # pad & truncate sequence
        news_as_word_ids.append(pad_sequence(word_ids, max_article_len))

    # reformat as array
    news_as_word_ids = np.array(news_as_word_ids, dtype='int32')

    return vocab, news_as_word_ids, art_id2idx

def get_embeddings_from_pretrained(vocab, emb_path, emb_dim=300):
    try:
        ft = fasttext.load_model(emb_path) # load pretrained vectors

        # check & adjust dimensionality
        if ft.get_dimension() != emb_dim:
            fasttext.util.reduce_model(ft, emb_dim)

        embedding_matrix = [0] * len(vocab)
        embedding_matrix[0] = np.zeros(emb_dim, dtype='float32')  # placeholder with zero values for 'PAD'

        for word, idx in vocab.items():
            embedding_matrix[idx] = ft[word] # how to deal with unknown words?

        return np.array(embedding_matrix, dtype='float32')

    except:
        print("Could not load word embeddings")

        return None

def generate_batch_data_test(all_test_pn, all_label, all_test_id, batch_size, all_test_user_pos, news_words):
    inputid = np.arange(len(all_label))
    y = all_label
    batches = [inputid[range(batch_size * i, min(len(y), batch_size * (i + 1)))] for i in
               range(len(y) // batch_size + 1)]

    while (True):
        for i in batches:
            candidate = news_words[all_test_pn[i]]
            browsed_news = news_words[all_test_user_pos[i]]
            browsed_news_split = [browsed_news[:, k, :] for k in range(browsed_news.shape[1])]
            userid = np.expand_dims(all_test_id[i], axis=1)
            label = all_label[i]

            yield ([candidate] + browsed_news_split + [userid], label)

def gen_batch_data(data, news_as_word_ids, batch_size=100, shuffle=True):

    #TODO: implement nice and more general dataloader
    n_batches = range(len(data) // batch_size + 1)

    if shuffle:
        random.shuffle(data)

    batches = [(batch_size * i, min(len(data), batch_size * (i + 1))) for i in
               n_batches]

    for start, stop in batches:
        # get data for this batch
        users, hist, cands, labels = zip(*[(data_p['input'][0], news_as_word_ids[data_p['input'][1]],
                                            news_as_word_ids[data_p['input'][2]], data_p['labels'])
                                                for data_p in data[start:stop]]) #return multiple lists from list comprehension

        # get candidates
        candidates = np.array(cands) # shape: batch_size X n_candidates X title_len
        candidates_split = [candidates[:, k, :] for k in range(candidates.shape[1])] # candidate_split[0].shape := (batch_size, max_title_len)

        # get history
        hist = np.array(hist)  # shape: batch_size X max_hist_len X max_title_len
        history_split = [hist[:, k, :] for k in range(hist.shape[1])]  # shape := (batch_size, max_title_len)

        # get user ids
        user_ids = np.expand_dims(np.array(users), axis=1)

        # get labels
        labels = np.array(labels)


        # aggregate to batch
        batch = (candidates_split + history_split + [user_ids], labels)

        yield batch

def gen_batch_data_test(data, news_as_word_ids, batch_size=100, candidate_pos=0):
    n_batches = range(len(data) // batch_size + 1)

    batches = [(batch_size * i, min(len(data), batch_size * (i + 1))) for i in
               n_batches]

    for start, stop in batches:
        # get data for this batch
        users, hist, cands, labels = zip(*[(data_p['input'][0], news_as_word_ids[data_p['input'][1]],
                                            news_as_word_ids[data_p['input'][2]], data_p['labels'])
                                                for data_p in data[start:stop]]) #return multiple lists from list comprehension

        # get candidates
        candidates = np.array(cands)  # shape: batch_size X n_candidates X title_len
        candidate = candidates[:, candidate_pos, :]  # candidate.shape := (batch_size, max_title_len)

        # get history
        hist = np.array(hist)  # shape: batch_size X max_hist_len X max_title_len
        history_split = [hist[:, k, :] for k in range(hist.shape[1])]  # shape := (batch_size, max_title_len)

        # get user ids
        user_ids = np.expand_dims(np.array(users), axis=1)

        # get labels
        labels = np.array(labels)
        labels = labels[:, candidate_pos]

    yield ([candidate] + history_split + [user_ids], labels)

def get_labels_from_data(data):
    labels = {}
    for entry_dict in data: #columns = ["u_id", "history", "candidates", "labels"]
        labels[entry_dict['u_id']] = entry_dict['labels']
    return labels

def get_dpg_data_processed(data_path, neg_sample_ratio=4, max_hist_len=50, max_article_len=30, min_counts_for_vocab=2, load_prepped=False):

    if load_prepped:
        try:
            with open(data_path + "news_prepped.pkl", 'rb') as fin:
                (vocab, news_as_word_ids, art_id2idx) = pickle.load(fin)

            with open(data_path + "data_prepped.pkl", 'rb') as fin:
                u_id2idx, data = pickle.load(fin)

            return data, vocab, news_as_word_ids, art_id2idx, u_id2idx
        except:
            print("Could not load preprocessed files! Continuing preprocessing now..")

    path_article_data = data_path + "news_data.pkl"

    vocab, news_as_word_ids, art_id2idx = preprocess_dpg_news_file(news_file=path_article_data,
                                                                   tokenizer=word_tokenize,
                                                                   min_counts_for_vocab=min_counts_for_vocab,
                                                                   max_article_len=max_article_len)

    with open(data_path + "news_prepped.pkl", 'wb') as fout:
        pickle.dump((vocab, news_as_word_ids, art_id2idx), fout)

    path_user_data = data_path + "user_data.pkl"

    u_id2idx, data = prep_dpg_user_file_wu(path_user_data, path_article_data, art_id2idx, test_interval_days=7,
                                           neg_sample_ratio=neg_sample_ratio, max_hist_len=max_hist_len)

    with open(data_path + "data_prepped.pkl", 'wb') as fout:
        pickle.dump((u_id2idx, data), fout)

    return data, vocab, news_as_word_ids, art_id2idx, u_id2idx

def init_weights(m):
    if isinstance(m, nn.Linear):
        torch.nn.init.xavier_uniform_(m.weight)
        m.bias.data.fill_(0.01)
    if isinstance(m, nn.Conv1d):
        torch.nn.init.xavier_uniform_(m.weight)
        if m.bias is not None:
            torch.nn.init.zeros_(m.bias)
    if isinstance(m, nn.Conv2d):
        torch.nn.init.xavier_uniform_(m.weight)
        if m.bias is not None:
            torch.nn.init.zeros_(m.bias)


def preprocess_user_file_wu(data_path='ClickData4.tsv', npratio=4):
    '''
    Original preprocessing function from Wu et al. (NPA, 2019)

    :param file:
    :param npratio:
    :return:
    '''

    file_name = FILE_NAMES_NPA['click']

    userid_dict = {}
    with open(data_path + file_name) as f:
        userdata = f.readlines()
    for user in userdata:
        line = user.strip().split('\t')
        userid = line[0]
        # map user_id to index
        if userid not in userid_dict:
            userid_dict[userid] = len(userid_dict)

    all_train_id = []
    all_train_pn = []
    all_label = []

    all_test_id = []
    all_test_pn = []
    all_test_label = []
    all_test_index = []

    all_user_pos = []
    all_test_user_pos = []

    for user in userdata:
        line = user.strip().split('\t')
        userid = line[0]
        # split userdata in impressions
        if len(line) == 4:
            impre = [x.split('#TAB#') for x in line[2].split('#N#')]
        if len(line) == 3:
            impre = [x.split('#TAB#') for x in line[2].split('#N#')]

        trainpos = [x[0].split() for x in impre]
        trainneg = [x[1].split() for x in impre]

        poslist = list(itertools.chain(*(trainpos)))
        neglist = list(itertools.chain(*(trainneg)))

        if len(line) == 4:
            testimpre = [x.split('#TAB#') for x in line[3].split('#N#')]
            testpos = [x[0].split() for x in testimpre]
            testneg = [x[1].split() for x in testimpre]

            for i in range(len(testpos)):
                sess_index = []
                sess_index.append(len(all_test_pn))
                posset = list(set(poslist))
                allpos = [int(p) for p in random.sample(posset, min(50, len(posset)))[:50]]
                allpos += [0] * (50 - len(allpos))

                for j in testpos[i]:
                    all_test_pn.append(int(j))
                    all_test_label.append(1)
                    all_test_id.append(userid_dict[userid])
                    all_test_user_pos.append(allpos)

                for j in testneg[i]:
                    all_test_pn.append(int(j))
                    all_test_label.append(0)
                    all_test_id.append(userid_dict[userid])
                    all_test_user_pos.append(allpos)
                sess_index.append(len(all_test_pn))
                all_test_index.append(sess_index) # record the indices for one user session

                '''
                later, these test instances are used as follows: 
                
                for m in all_test_index:
                    if np.sum(all_test_label[m[0]:m[1]])!=0 and m[1]<len(click_score):
                        all_auc.append(roc_auc_score(all_test_label[m[0]:m[1]],click_score[m[0]:m[1],0]))
                        all_mrr.append(mrr_score(all_test_label[m[0]:m[1]],click_score[m[0]:m[1],0]))
                '''

        for impre_id in range(len(trainpos)):
            for pos_sample in trainpos[impre_id]:

                pos_neg_sample = sample_n_from_elements(trainneg[impre_id], npratio)
                pos_neg_sample.append(pos_sample)
                temp_label = [0] * npratio + [1]
                temp_id = list(range(npratio + 1))
                random.shuffle(temp_id)

                shuffle_sample = []
                shuffle_label = []
                for id in temp_id:
                    shuffle_sample.append(int(pos_neg_sample[id]))
                    shuffle_label.append(temp_label[id])

                posset = list(set(poslist) - set([pos_sample]))
                allpos = [int(p) for p in random.sample(posset, min(50, len(posset)))[:50]]
                allpos += [0] * (50 - len(allpos))
                all_train_pn.append(shuffle_sample)
                all_label.append(shuffle_label)
                all_train_id.append(userid_dict[userid])
                all_user_pos.append(allpos)

    all_train_pn = np.array(all_train_pn, dtype='int32')
    all_label = np.array(all_label, dtype='int32')
    all_train_id = np.array(all_train_id, dtype='int32')
    all_test_pn = np.array(all_test_pn, dtype='int32')
    all_test_label = np.array(all_test_label, dtype='int32')
    all_test_id = np.array(all_test_id, dtype='int32')
    all_user_pos = np.array(all_user_pos, dtype='int32')
    all_test_user_pos = np.array(all_test_user_pos, dtype='int32')
    return userid_dict, all_train_pn, all_label, all_train_id, all_test_pn, all_test_label, all_test_id, all_user_pos, all_test_user_pos, all_test_index


def main(config):
    '''
    holthaus
    '''

    if config.data_type not in DATA_TYPES:
        raise KeyError("{} is not a known data format".format(config.data_type))

    if config.data_type == "DPG":
        # use DPG data

        # load & prep news data
        vocab, news_as_word_ids, art_id2idx = preprocess_dpg_news_file(news_file=config.article_data,
                                                                       tokenizer=word_tokenize,
                                                                       min_counts_for_vocab=2,
                                                                       max_article_len=30)

        with open(config.data_path + "news_prepped.pkl", 'wb') as fout:
            pickle.dump((vocab, news_as_word_ids, art_id2idx), fout)

        u_id2idx, data = prep_dpg_user_file_wu(config.user_data, set(art_id2idx.keys()), art_id2idx, neg_sample_ratio=config.neg_sample_ratio, max_hist_len=config.max_hist_len)

        #idx2u_id = reverse_mapping_dict(u_id2idx)
        #idx2art_id = reverse_mapping_dict(art_id2idx)

        train_data, test_data = train_test_split(data, test_size=0.2, shuffle=True, random_state=42)

        batch = gen_batch_data(train_data, news_as_word_ids, batch_size=100)


    elif config.data_type == "Adressa":
        # use Adressa data
        raise NotImplementedError()

    elif config.data_type == "NPA":
        config.data_path = "../datasets/NPA/"
        preprocess_user_file_wu(config.data_path)




if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    # input data
    parser.add_argument('--data_type', type=str, default='NPA',
                        help='options for data format: DPG, NPA or Adressa ')
    parser.add_argument('--data_path', type=str, default='../datasets/dpg/i10k_u5k_s30/',
                        help='path to data directory') #dpg/i10k_u5k_s30/

    parser.add_argument('--article_ids', type=str, default='../datasets/dpg/i10k_u5k_s30/item_ids.pkl',
                        help='path to directory with item id pickle file')
    parser.add_argument('--article_data', type=str, default='../datasets/dpg/i10k_u5k_s30/news_data.pkl',
                        help='path to article data pickle file')
    parser.add_argument('--user_data', type=str, default='../datasets/dpg/i10k_u5k_s30/user_data.pkl',
                        help='path to user data pickle file')

    parser.add_argument('--word_emb_path', type=str, default='../embeddings/glove_eng.840B.300d.txt',
                        help='path to directory with word embeddings')

    parser.add_argument('--pkl_path', type=str, default='../datasets/books-pickle/', help='path to save pickle files')

    # preprocessing
    parser.add_argument('--max_hist_len', type=int, default=50,
                        help='maximum length of user reading history, shorter ones are padded; should be in accordance with the input datasets')

    parser.add_argument('--neg_sample_ratio', type=int, default=4,
                        help='Negative sample ratio N: for each positive impression generate N negative samples')

    config = parser.parse_args()

    main(config)
