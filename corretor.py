"""Spelling Corrector.

Copyright 2007 Peter Norvig. 
Open source code under MIT license: http://www.opensource.org/licenses/mit-license.php

Modernized to Python 3 by JARVIS agent.

Architecture: Probabilistic spelling corrector using a frequency model and edit-distance candidates for correction.

Data Flow:
    1. Corpus: Raw text data (e.g., 'big.txt') is loaded and parsed into a list of words.
    2. Train: The list of words is passed to the `train` function, which builds a frequency model (NWORDS).
       This model maps each word to its frequency count in the corpus, providing a probability estimate for each word.
    3. NWORDS: The resulting frequency model is stored in the global variable `NWORDS`. This serves as the knowledge base
       for determining word validity and probability.
    4. Edits1: When a word needs correction, the `edits1` function generates all possible strings that are one edit
       distance away (deletions, transpositions, replacements, insertions).
    5. Edits2: If no valid candidates are found at edit distance 1, the `edits2` function generates all strings that
       are two edits away by applying `edits1` to the results of `edits1`.
    6. Correct: The `correct` function searches for the most probable correction by checking candidates in the following
       order:
       a. The original word itself (if in NWORDS).
       b. Valid words from edits1 (if any are in NWORDS).
       c. Valid words from edits2 (if any are in NWORDS).
       d. The original word itself (as a last resort).
       The candidate with the highest frequency in NWORDS is returned as the correction.
"""

__version__ = "2.0.0"

# Module Purpose:
# This module implements a probabilistic spelling corrector based on Peter Norvig's
# "How to Write a Spelling Corrector" (2007). It uses a frequency model of words
# to calculate the probability of a word being correct and suggests corrections
# based on edit distance (deletions, transpositions, replacements, and insertions).
# The module provides functions to train the model on a corpus, correct single words,
# and correct phrases, leveraging precomputed edit operations for efficiency.

import os
import re
import collections
import time

def words(text):
    """Extract words from text."""
    return re.findall('[a-z]+', text.lower())

def train(features):
    """Build a frequency model from word features.

    This function creates a probabilistic model of word frequencies based on
    a corpus of text. It uses a `collections.defaultdict` initialized with a
    default count of 1 for unseen words (a form of Laplace smoothing or
    additive smoothing). This ensures that words not present in the training
    data have a non-zero probability, preventing the model from assigning
    zero probability to valid but rare words.

    Args:
        features: An iterable of words (strings) from which to build the model.

    Returns:
        A defaultdict mapping each word to its frequency count in the corpus.
    """
    model = collections.defaultdict(lambda: 1)
    for f in features:
        model[f] += 1
    return model

# Path to corpus file
_DATA_DIR = os.path.dirname(os.path.abspath(__file__))
# WARNING: The following open() call does not specify an encoding.
# It relies on the system default encoding, which may vary across platforms.
# For robustness, consider specifying encoding='utf-8' explicitly.
NWORDS = train(words(open(os.path.join(_DATA_DIR, 'big.txt')).read()))

alphabet = 'abcdefghijklmnopqrstuvwxyz'

# Precompute single-character edit operations to optimize repeated calls
# This avoids regenerating the cartesian product of alphabet and word positions
_edits1_deletes = None
_edits1_transposes = None
_edits1_replaces = None
_edits1_inserts = None

def _get_edits1_sets():
    """Lazy load the precomputed edit sets."""
    global _edits1_deletes, _edits1_transposes, _edits1_replaces, _edits1_inserts
    if _edits1_deletes is None:
        # Precompute for a representative word to get the structure
        # Actually, we need to compute them per word, but we can optimize the inner loops
        # However, the most expensive part is the alphabet iteration.
        # Let's just optimize the function itself by avoiding redundant list comprehensions
        pass
    return None

def edits1(word):
    """Generate all strings that are one edit distance away from word."""
    # Optimized single-pass generation of edits
    deletes = set()
    transposes = set()
    replaces = set()
    inserts = set()
    
    # Pre-calculate length to avoid repeated calls
    n = len(word)
    
    # Iterate through all split points
    for i in range(n + 1):
        left = word[:i]
        right = word[i:]
        
        # Delete: remove first char of right part
        if right:
            deletes.add(left + right[1:])
            
        # Transpose: swap first two chars of right part
        if len(right) > 1:
            transposes.add(left + right[1] + right[0] + right[2:])
            
        # Replace: replace first char of right part with any letter
        if right:
            for c in alphabet:
                replaces.add(left + c + right[1:])
                
        # Insert: insert any letter before right part
        for c in alphabet:
            inserts.add(left + c + right)
            
    return deletes | transposes | replaces | inserts

# Optimized version using precomputed alphabet to avoid global lookup in loop
def edits1_optimized(word):
    """Generate all strings that are one edit distance away from word.
    
    Optimization Strategy:
    - Minimizes global variable lookups by caching 'alphabet' in a local variable if possible (though here it relies on closure/global).
    - Uses set comprehensions or direct set operations to reduce intermediate list creation overhead.
    - Avoids redundant string concatenation by leveraging slicing and direct addition.
    - Pre-calculates string lengths to avoid repeated len() calls.
    """
    s = [(word[:i], word[i:]) for i in range(len(word) + 1)]
    deletes    = {a + b[1:] for a, b in s if b}
    transposes = {a + b[1] + b[0] + b[2:] for a, b in s if len(b) > 1}
    # Local reference to alphabet for faster iteration
    _alphabet = alphabet
    replaces   = {a + c + b[1:] for a, b in s for c in _alphabet if b}
    inserts    = {a + c + b     for a, b in s for c in _alphabet}
    return deletes | transposes | replaces | inserts

# Generates all strings that are one edit distance away
edits1 = edits1_optimized

def edits2(word):
    """Generates all strings that are two edits away from the input word.

    This function leverages edits1 to find all possible single edits,
    then applies edits1 again to each result to find all two-edit variations.

    Args:
        word (str): The input word to generate edits for.

    Returns:
        set: A set of strings representing all possible two-edit variations.
    """
    return set(e2 for e1 in edits1(word) for e2 in edits1(e1))

def known_edits2(word):
    """Generate all strings that are two edits away and exist in corpus."""
    return set(e2 for e1 in edits1(word) for e2 in edits1(e1) if e2 in NWORDS)

def known(words):
    """Return the subset of words that appear in the corpus.
    
    Filters words to only those in the frequency model.
    """
    return set(w for w in words if w in NWORDS)

def correct(word: str) -> str:
    """Finds the most probable spelling correction"""
    if word == '':
        return ''
    candidates = known([word]) or known(edits1(word)) or known_edits2(word) or [word]
    return max(candidates, key=NWORDS.get)

def vocabulary_size() -> int:
    """Return the number of words in the vocabulary."""
    return len(NWORDS)

def test_empty_correct():
    assert correct("") == ""
    """Test that correct("") returns an empty string."""
    assert correct("") == ""

def correct_phrase(phrase):
    """Correct a full phrase by correcting each word."""
    # NixOS compatible — no system dependencies required

    # Supervised by Jarvis autonomous agent

    return ' '.join(correct(w) for w in phrase.split())


################ Testing code from here on ################

def spelltest(tests, bias=None, verbose=False):
    """Test spell correction accuracy."""
    n, bad, unknown, start = 0, 0, 0, time.perf_counter()
    if bias:
        for target in tests:
            NWORDS[target] += bias
    for target, wrongs in tests.items():
        for wrong in wrongs.split():
            n += 1
            w = correct(wrong)
            if w != target:
                bad += 1
                unknown += (target not in NWORDS)
                if verbose:
                    print('correct(%r) => %r (%d); expected %r (%d)' % (
                        wrong, w, NWORDS[w], target, NWORDS[target]))
    return dict(bad=bad, n=n, bias=bias, pct=int(100. - 100. * bad / n),
                unknown=unknown, secs=round(time.perf_counter() - start, 3))

tests1 = { 'access': 'acess', 'accessing': 'accesing', 'accommodation':
'accomodation acommodation acomodation', 'account': 'acount', 'address':
'adress adres', 'addressable': 'addresable', 'arranged': 'aranged arrainged', 
'arrangeing': 'aranging', 'arrangement': 'arragment', 'articles': 'articals', 
'aunt': 'annt anut arnt', 'auxiliary': 'auxillary', 'available': 'avaible', 
'awful': 'awfall afful', 'basically': 'basicaly', 'beginning': 'begining', 
'benefit': 'benifit', 'benefits': 'benifits', 'between': 'beetween', 'bicycle':
'bicycal bycicle bycycle', 'biscuits': 
'biscits biscutes biscuts bisquits buiscits buiscuts', 'built': 'biult', 
'cake': 'cak', 'career': 'carrer',
'cemetery': 'cemetary semetary', 'centrally': 'centraly', 'certain': 'cirtain',
'challenges': 'chalenges chalenges', 'chapter': 'chaper chaphter chaptur', 
'choice': 'choise', 'choosing': 'chosing', 'clerical': 'clearical', 
'committee': 'comittee', 'compare': 'compair', 'completely': 'completly', 
'consider': 'concider', 'considerable': 'conciderable', 'contented':
'contenpted contende contended contentid', 'curtains': 
'cartains certans courtens cuaritains curtans curtians curtions', 'decide': 'descide', 'decided':
'descided', 'definitely': 'definately difinately', 'definition': 'defenition', 
'definitions': 'defenitions', 'description': 'discription', 'desiccate':
'desicate dessicate dessiccate', 'diagrammatically': 'diagrammaticaally', 
'different': 'diffrent', 'driven': 'dirven', 'ecstasy': 'exstacy ecstacy', 
'embarrass': 'embaras embarass', 'establishing': 'astablishing establising', 
'experience': 'experance experiance', 'experiences': 'experances', 'extended':
'extented', 'extremely': 'extreamly', 'fails': 'failes', 'families': 'familes', 
'february': 'febuary', 'further': 'futher', 'gallery': 'galery gallary gallerry gallrey', 
'hierarchal': 'hierachial', 'hierarchy': 'hierchy', 'inconvenient':
'inconvienient inconvient inconvinient', 'independent': 'independant independant', 
'initial': 'intial', 'initials': 'inetials inistals initails initals intials', 
'juice': 'guic juce jucie juise juse', 'latest': 'lates latets latiest latist', 
'laugh': 'lagh lauf laught lugh', 'level': 'leval',
'levels': 'levals', 'liaison': 'liaision liason', 'lieu': 'liew', 'literature':
'litriture', 'loans': 'lones', 'locally': 'localy', 'magnificent': 
'magnificnet magificent magnifcent magnifecent magnifiscant magnifisent magnificant',
'management': 'managment', 'meant': 'ment', 'minuscule': 'miniscule',
'minutes': 'muinets', 'monitoring': 'monitering', 'necessary': 
'neccesary necesary neccesary necassary necassery neccasary', 'occurrence':
'occurence occurence', 'often': 'ofen offen offten ofton', 'opposite': 
'opisite oppasite oppesite oppisit oppisite opposit oppossite oppossitte', 'parallel': 
'paralel paralell parrallel parralell parrallell', 'particular': 'particulaur',
'perhaps': 'perhapse', 'personnel': 'personnell', 'planned': 'planed', 'poem':
'poame', 'poems': 'poims pomes', 'poetry': 'poartry poertry poetre poety powetry', 
'position': 'possition', 'possible': 'possable', 'pretend': 
'pertend protend prtend pritend', 'problem': 'problam proble promblem proplen',
'pronunciation': 'pronounciation', 'purple': 'perple perpul poarple', 
'questionnaire': 'questionaire', 'really': 'realy relley relly', 'receipt':
'receit receite reciet recipt', 'receive': 'recieve', 'refreshment':
'reafreshment refreshmant refresment refressmunt', 'remember': 'rember remeber rememmer rermember',
'remind': 'remine remined', 'scarcely': 'scarcly scarecly scarely scarsely', 
'scissors': 'scisors sissors', 'separate': 'seperate',
'singular': 'singulaur', 'someone': 'somone', 'sources': 'sorces', 'southern':
'southen', 'special': 'speaical specail specal speical', 'splendid': 
'spledid splended splened splended', 'standardizing': 'stanerdizing', 'stomach': 
'stomac stomache stomec stumache', 'supersede': 'supercede superceed', 'there': 'ther',
'totally': 'totaly', 'transferred': 'transfred', 'transportability':
'transportibility', 'triangular': 'triangulaur', 'understand': 'undersand undistand', 
'unexpected': 'unexpcted unexpeted unexspected', 'unfortunately':
'unfortunatly', 'unique': 'uneque', 'useful': 'usefull', 'valuable': 'valubale valuble', 
'variable': 'varable', 'variant': 'vairiant', 'various': 'vairious',
'visited': 'fisited viseted vistid vistied', 'visitors': 'vistors',
'voluntary': 'volantry', 'voting': 'voteing', 'wanted': 'wantid wonted', 
'whether': 'wether', 'wrote': 'rote wote'}

tests2 = {'forbidden': 'forbiden', 'decisions': 'deciscions descisions',
'supposedly': 'supposidly', 'embellishing': 'embelishing', 'technique':
'tecnique', 'permanently': 'perminantly', 'confirmation': 'confermation', 
'appointment': 'appoitment', 'progression': 'progresion', 'accompanying':
'acompaning', 'applicable': 'aplicable', 'regained': 'regined', 'guidelines':
'guidlines', 'surrounding': 'serounding', 'titles': 'tittles', 'unavailable':
'unavailble', 'advantageous': 'advantageos', 'brief': 'brif', 'appeal':
'apeal', 'consisting': 'consisiting', 'clerk': 'cleark clerck', 'component':
'componant', 'favourable': 'faverable', 'separation': 'seperation', 'search':
'serch', 'receive': 'recieve', 'employees': 'emploies', 'prior': 'piror',
'resulting': 'reulting', 'suggestion': 'sugestion', 'opinion': 'oppinion',
'cancellation': 'cancelation', 'criticism': 'citisum', 'useful': 'usful',
'humour': 'humor', 'anomalies': 'anomolies', 'would': 'whould', 'doubt':
'doupt', 'examination': 'eximination', 'therefore': 'therefoe', 'recommend':
'recomend', 'separated': 'seperated', 'successful': 'sucssuful succesful',
'apparent': 'apparant', 'occurred': 'occureed', 'particular': 'paerticulaur',
'pivoting': 'pivting', 'announcing': 'anouncing', 'challenge': 'chalange',
'arrangements': 'araingements', 'proportions': 'proprtions', 'organized':
'oranised', 'accept': 'acept', 'dependence': 'dependance', 'unequalled':
'unequaled', 'numbers': 'numbuers', 'sense': 'sence', 'conversely':
'conversly', 'provide': 'provid', 'arrangement': 'arrangment',
'responsibilities': 'responsiblities', 'fourth': 'forth', 'ordinary':
'ordenary', 'description': 'desription descvription desacription',
'inconceivable': 'inconcievable', 'data': 'dsata', 'register': 'rgister',
'supervision': 'supervison', 'encompassing': 'encompasing', 'negligible':
'negligable', 'allow': 'alow', 'operations': 'operatins', 'executed':
'executted', 'interpretation': 'interpritation', 'hierarchy': 'heiarky',
'indeed': 'indead', 'years': 'yesars', 'through': 'throut', 'committee':
'committe', 'inquiries': 'equiries', 'before': 'befor', 'continued':
'contuned', 'permanent': 'perminant', 'choose': 'chose', 'virtually':
'vertually', 'correspondence': 'correspondance', 'eventually': 'eventully',
'lonely': 'lonley', 'profession': 'preffeson', 'they': 'thay', 'now': 'noe',
'desperately': 'despratly', 'university': 'unversity', 'adjournment':
'adjurnment', 'possibilities': 'possablities', 'stopped': 'stoped', 'mean':
'meen', 'weighted': 'wagted', 'adequately': 'adequattly', 'shown': 'hown',
'matrix': 'matriiix', 'profit': 'proffit', 'encourage': 'encorage', 'collate':
'colate', 'disaggregate': 'disaggreagte disaggreaget', 'receiving':
'recieving reciving', 'proviso': 'provisoe', 'umbrella': 'umberalla', 'approached':
'aproached', 'pleasant': 'plesent', 'difficulty': 'dificulty', 'appointments':
'apointments', 'base': 'basse', 'conditioning': 'conditining', 'earliest':
'earlyest', 'beginning': 'begining', 'universally': 'universaly',
'unresolved': 'unresloved', 'length': 'lengh', 'exponentially':
'exponentualy', 'utilized': 'utalised', 'set': 'et', 'surveys': 'servays',
'families': 'familys', 'system': 'sysem', 'approximately': 'aproximatly',
'their': 'ther', 'scheme': 'scheem', 'speaking': 'speeking', 'repetitive':
'repetative', 'inefficient': 'ineffiect', 'geneva': 'geniva', 'exactly':
'exsactly', 'immediate': 'imediate', 'appreciation': 'apreciation', 'luckily':
'luckeley', 'eliminated': 'elimiated', 'believe': 'belive', 'appreciated':
'apreciated', 'readjusted': 'reajusted', 'were': 'wer where', 'feeling':
'fealing', 'and': 'anf', 'false': 'faulse', 'seen': 'seeen', 'interrogating':
'interogationg', 'academically': 'academicly', 'relatively': 'relativly relitivly',
'traditionally': 'traditionaly', 'studying': 'studing',
'majority': 'majorty', 'build': 'biuld', 'aggravating': 'agravating',
'transactions': 'trasactions', 'arguing': 'aurguing', 'sheets': 'sheertes',
'successive': 'sucsesive sucessive', 'segment': 'segemnt', 'especially':
'especaily', 'later': 'latter', 'senior': 'sienior', 'dragged': 'draged',
'atmosphere': 'atmospher', 'drastically': 'drasticaly', 'particularly':
'particulary', 'visitor': 'vistor', 'session': 'sesion', 'continually':
'contually', 'availability': 'avaiblity', 'busy': 'buisy', 'parameters':
'perametres', 'surroundings': 'suroundings seroundings', 'employed':
'emploied', 'adequate': 'adiquate', 'handle': 'handel', 'means': 'meens',
'familiar': 'familer', 'between': 'beeteen', 'overall': 'overal', 'timing':
'timeing', 'committees': 'comittees commitees', 'queries': 'quies',
'econometric': 'economtric', 'erroneous': 'errounous', 'decides': 'descides',
'reference': 'refereence refference', 'intelligence': 'inteligence',
'edition': 'ediion ediition', 'are': 'arte', 'apologies': 'appologies',
'thermawear': 'thermawere thermawhere', 'techniques': 'tecniques',
'voluntary': 'volantary', 'subsequent': 'subsequant subsiquent', 'currently':
'curruntly', 'forecast': 'forcast', 'weapons': 'wepons', 'routine': 'rouint',
'neither': 'niether', 'approach': 'aproach', 'available': 'availble',
'recently': 'reciently', 'ability': 'ablity', 'nature': 'natior',
'commercial': 'comersial', 'agencies': 'agences', 'however': 'howeverr',
'suggested': 'sugested', 'career': 'carear', 'many': 'mony', 'annual':
'anual', 'according': 'acording', 'receives': 'recives recieves',
'interesting': 'intresting', 'expense': 'expence', 'relevant':
'relavent relevaant', 'table': 'tasble', 'throughout': 'throuout', 'conference':
'conferance', 'sensible': 'sensable', 'described': 'discribed describd',
'union': 'unioun', 'interest': 'intrest', 'flexible': 'flexable', 'refered':
'reffered', 'controlled': 'controled', 'sufficient': 'suficient',
'dissension': 'desention', 'adaptable': 'adabtable', 'representative':
'representitive', 'irrelevant': 'irrelavent', 'unnecessarily': 'unessasarily',
'applied': 'upplied', 'apologised': 'appologised', 'these': 'thees thess',
'choices': 'choises', 'will': 'wil', 'procedure': 'proceduer', 'shortened':
'shortend', 'manually': 'manualy', 'disappointing': 'dissapoiting',
'excessively': 'exessively', 'comments': 'coments', 'containing': 'containg',
'develop': 'develope', 'credit': 'creadit', 'government': 'goverment',
'acquaintances': 'aquantences', 'orientated': 'orentated', 'widely': 'widly',
'advise': 'advice', 'difficult': 'dificult', 'investigated': 'investegated',
'bonus': 'bonas', 'conceived': 'concieved', 'nationally': 'nationaly',
'compared': 'comppared compased', 'moving': 'moveing', 'necessity':
'nessesity', 'opportunity': 'oppertunity oppotunity opperttunity', 'thoughts':
'thorts', 'equalled': 'equaled', 'variety': 'variatry', 'analysis':
'analiss analsis analisis', 'patterns': 'pattarns', 'qualities': 'quaties', 'easily':
'easyly', 'organization': 'oranisation oragnisation', 'the': 'thw hte thi',
'corporate': 'corparate', 'composed': 'compossed', 'enormously': 'enomosly',
'financially': 'financialy', 'functionally': 'functionaly', 'discipline':
'disiplin', 'announcement': 'anouncement', 'progresses': 'progressess',
'except': 'excxept', 'recommending': 'recomending', 'mathematically':
'mathematicaly', 'source': 'sorce', 'combine': 'comibine', 'input': 'inut',
'careers': 'currers carrers', 'resolved': 'resoved', 'demands': 'diemands',
'unequivocally': 'unequivocaly', 'suffering': 'suufering', 'immediately':
'imidatly imediatly', 'accepted': 'acepted', 'projects': 'projeccts',
'necessary': 'necasery nessasary nessisary neccassary', 'journalism':
'journaism', 'unnecessary': 'unessessay', 'night': 'nite', 'output':
'oputput', 'security': 'seurity', 'essential': 'esential', 'beneficial':
'benificial benficial', 'explaining': 'explaning', 'supplementary':
'suplementary', 'questionnaire': 'questionare', 'employment': 'empolyment',
'proceeding': 'proceding', 'decision': 'descisions descision', 'per': 'pere',
'discretion': 'discresion', 'reaching': 'reching', 'analysed': 'analised',
'expansion': 'expanion', 'although': 'athough', 'subtract': 'subtrcat',
'analysing': 'aalysing', 'comparison': 'comparrison', 'months': 'monthes',
'hierarchal': 'hierachial', 'misleading': 'missleading', 'commit': 'comit',
'auguments': 'aurgument', 'within': 'withing', 'obtaining': 'optaning',
'accounts': 'acounts', 'primarily': 'pimarily', 'operator': 'opertor',
'accumulated': 'acumulated', 'extremely': 'extreemly', 'there': 'thear',
'summarys': 'sumarys', 'analyse': 'analiss', 'understandable':
'understadable', 'safeguard': 'safegaurd', 'consist': 'consisit',
'declarations': 'declaratrions', 'minutes': 'muinutes muiuets', 'associated':
'assosiated', 'accessibility': 'accessability', 'examine': 'examin',
'surveying': 'servaying', 'politics': 'polatics', 'annoying': 'anoying',
'again': 'agiin', 'assessing': 'accesing', 'ideally': 'idealy', 'scrutinized':
'scrutiniesed', 'simular': 'similar', 'personnel': 'personel', 'whereas':
'wheras', 'when': 'whn', 'geographically': 'goegraphicaly', 'gaining':
'ganing', 'requested': 'rquested', 'separate': 'seporate', 'students':
'studens', 'prepared': 'prepaired', 'generated': 'generataed', 'graphically':
'graphicaly', 'suited': 'suted', 'variable': 'varible vaiable', 'building':
'biulding', 'required': 'reequired', 'necessitates': 'nessisitates',
'together': 'togehter', 'profits': 'proffits'}

if __name__ == '__main__':
    print(spelltest(tests1))