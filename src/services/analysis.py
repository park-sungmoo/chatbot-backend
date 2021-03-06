from collections import Counter, OrderedDict

import config
import numpy as np
from src.data.query import QueryMaker
from src.data.preprocessor import PreProcessor
from src.db.queries import index as _query
from src.db.questions import index as _questions
from sklearn.manifold import TSNE
import matplotlib.pyplot as plt
from src.model.serving import TensorServer
from sklearn.metrics import pairwise_distances

_tensor_server = TensorServer()
_query_maker = QueryMaker()
_preprocessor = PreProcessor()

CONFIG = config.ANALYSIS


# plt.rcParams["font.family"] = 'NanumGothic'
# plt.rcParams["font.size"] = 5
# plt.rcParams['figure.figsize'] = (15, 15)


def get_Morphs(query):
    query, removed = _preprocessor.clean(query)
    output = _preprocessor.get_morphs(query)
    output['removed'] = removed
    return output


def get_JaccardSimilarity(query):
    query, removed = _preprocessor.clean(query)
    sorted_jaccard_list = _query_maker.get_jaccard(query)

    output = {
        'query': query,
        'removed': removed,
        'question_1': {
            'text': None,
            'only_in_query': None,
            'only_in_question': None,
            'in_both': None,
            'score': None
        },
        'question_2': {
            'text': None,
            'only_in_query': None,
            'only_in_question': None,
            'in_both': None,
            'score': None
        },
        'question_3': {
            'text': None,
            'only_in_query': None,
            'only_in_question': None,
            'in_both': None,
            'score': None
        }
    }
    N = 1
    _morphs_query = _preprocessor.get_morphs(query)
    _length_query = len(_morphs_query)
    for key, score in sorted_jaccard_list.items():
        _morphs_question = _preprocessor.get_morphs(key)
        only_in_query = {}
        only_in_question = {}
        in_both = {}
        for word, tag in _morphs_query.items():
            if word == 'text':
                continue
            if word in _morphs_question.keys():
                in_both[word] = tag
            else:
                only_in_query[word] = tag

        for word, tag in _morphs_question.items():
            if word == 'text':
                continue
            if word not in in_both.keys():
                only_in_question[word] = tag

        output['question_{}'.format(N)] = {
            'text': key,
            'only_in_query': only_in_query,
            'only_in_question': only_in_question,
            'in_both': in_both,
            'score': score
        }
        N += 1
        if N == 4:
            break
    return output


def get_MostCommonKeywords(n=7, mode=0):
    field = {'keywords': 1}
    # 자주 나오는 키워드 Top
    if mode == 0:
        target_list = _questions.find(field)
    elif mode == 1:
        target_list = list(_query.collection.find({}, field))

    keywords = []
    for target in target_list:
        for keyword in target['keywords']:
            keywords.append(keyword)
    most_common = Counter(keywords).most_common(n)

    output = {}

    for key, value in most_common:
        output[key] = value

    return output


def get_SearchToQuestion(n=20):
    queries = _query.find_by_category('search')[:n]

    output = {}
    for query in queries:
        output[query.chat] = query.answer['answer']

    return output
    # search 중에서 정확도가 높은 것들을 사전 답변으로 옮기는 것을 고려


def visualize_similarity(chat, mode=0):
    """t-SNE 학습을 통해 벡터 시각화"""
    assert type(chat) == str
    tsne = TSNE(n_components=CONFIG['n_components'],
                perplexity=CONFIG['perplexity'],
                learning_rate=CONFIG['learning_rate'],
                n_iter=CONFIG['n_iter'],
                metric="precomputed",
                method=CONFIG['method'])
    X = []  # (n_samples, n_features)
    X_text = []
    X_category = []

    chat_vector = _query_maker.modelWrapper.similarity(chat=chat)
    chat_vector = _query_maker.get_weighted_average_vector(text=chat, vector=chat_vector)

    if mode == 0:
        target_list = _questions.find_all()
    if mode == 1:
        target_list = _query.find_all()

    X.append(chat_vector)
    X_text.append(chat)
    X_category.append('입력')

    for target in target_list:
        if mode == 0:
            text = target.text
        if mode == 1:
            text = target.chat
            # :( ㅜ_ㅜ

        if text in X_text:  # Save time
            continue
        if target.feature_vector is None:  # 에러
            continue
        question_vector = _query_maker.get_weighted_average_vector(text=text, vector=target.feature_vector)

        if type(question_vector) == np.ndarray:
            X.append(question_vector)
            X_text.append(text)
            X_category.append(target.category)

    X = pairwise_distances(X, X, metric=CONFIG['metric'], n_jobs=-1)

    Y = tsne.fit_transform(X=X)  # low-dimension vectors
    x = Y[:, 0]
    y = Y[:, 1]

    output = {}
    chat = []
    chat.append({'text': str(X_text[0]),
                 'x': str(x[0]),
                 'y': str(y[0])})
    output['input'] = chat
    for category in CONFIG['categories']:
        temp = []
        for i in range(len(X_category)):
            if X_category[i] == category:
                temp.append({'text': X_text[i],
                             'x': str(x[i]),
                             'y': str(y[i])})
        output[category] = temp

    # plt.scatter(x=x, y=y)
    # for i in range(len(x)):
    #     plt.text(x=x[i] + 0.1, y=y[i], s=X_text[i], fontsize=10)
    # plt.show()
    return output


def visualize_category(mode=0):
    field = {'category': 1}
    categories = []

    if mode == 0:  # Questions
        questions = list(_questions.collection.find({}, field))

        for question in questions:
            categories.append(question['category'])
    elif mode == 1:
        queries = _query.collection.find({}, field)

        for query in queries:
            categories.append(query['category'])

    counter = Counter(categories)
    return counter


def visualize_sentiment():
    queries = _query.find_all()

    output = OrderedDict()
    for query in queries:
        if query.chat in output:
            continue
        sentiment_score = _tensor_server.sentiment(query.chat)
        output[query.chat] = sentiment_score[0]
    output = sorted(output.items(), key=lambda x: x[1], reverse=True)
    return output


def get_FeatureSimilarity(text, n=10):
    feature_top_distances = _query_maker.make_query(text, analysis=True)
    if not feature_top_distances:
        return None
    output = {}

    if n > len(feature_top_distances):
        n = len(feature_top_distances)

    for i in range(n):
        matched_question_text = feature_top_distances[i][0].text
        matched_question_distance = feature_top_distances[i][1]

        output[i] = (matched_question_text, matched_question_distance)

    return output


if __name__ == '__main__':
    # print(get_JaccardSimilarity('셔틀 언제 오나요?'))
    # b = get_MostCommonKeywords()
    # print(get_SearchToQuestion())
    # output = visualize_similarity('셔틀 언제 와?', mode=1)
    # visualize_category(1)
    a = visualize_sentiment()
    pass
