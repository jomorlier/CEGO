# -*- coding: utf-8 -*-
"""
Created on Tue Oct 10 09:05:48 2017

@author: r.dewinter
"""
from JCS_LHSOptimizer import JCS_LHSOptimizer
from transformLHS import transformLHS
from simplexGauss import simplexGauss
from simplexKriging import simplexKriging
from predictorEGO import predictorEGO
from paretofrontFeasible import paretofrontFeasible
from optimizeSMSEGOcriterion import optimizeSMSEGOcriterion
from hypervolume import hypervolume
from findAllLocalOptimaNew3 import findAllLocalOptimaNew
from visualiseParetoFront import visualiseParetoFront
from RbfInter import trainCubicRBF
from RbfInter import adjustMargins

from functools import partial
import numpy as np
from scipy.special import ndtri
import os
import json
import copy
import time
import glob
import multiprocessing


def createKrigingModel(arguments):
    parameters, objectives, evall, i = arguments
    modell = simplexGauss(parameters[:evall,:], objectives[:evall,i])[0]
    temp = predictorEGO(parameters[:evall,:], modell)[0]
    modell = simplexGauss(parameters[:evall,:],temp,[1])[0]
    return modell

def createExpKrigingModel(arguments):
    parameters, objectives, evall, i = arguments
    modell = simplexKriging(parameters[:evall,:], objectives[:evall,i])[0]
    temp = predictorEGO(parameters[:evall,:], modell)[0]
    modell = simplexKriging(parameters[:evall,:], temp, [1])[0] 
    return modell
    
def CONSTRAINED_SMSEGO(problemCall, rngMin, rngMax, ref, nconstraints, initEval=None, maxEval=None, smooth=None, runNo=0, epsilonInit=0.01, epsilonMax=0.02):
    """
    based on: 
        
    1 Designing Ships using Constrained Multi-Objective Efficient Global Optimization
    Roy de Winter, Bas van Stein, Matthys Dijkman and Thomas Baeck
    In the Fourth international conference of machinelearning optimization and data science (2018)
    
    2 S-Metric Selection based Efficient Global Optimization (SMS-EGO) for
    multi-objective optimization problems
    Ponweiser, W.; Wagner, T.; Biermann, D.; Vincze, M.: Multiobjective
    Optimization on a Limited Amount of Evaluations Using Model-Assisted
    S-Metric Selection. In: Proc. 10th Int'l Conf. Parallel Problem Solving
    from Nature (PPSN X), 13.-17. September, Dortmund, Rudolph, G.; Jansen,
    T.; Lucas, S.; Poloni, C.; Beume, N. (Eds.). No. 5199 in Lecture Notes
    in Computer Science, Springer, Berlin, 2008, pp. 784-794.
    ISBN 978-3-540-87699-1. doi: 10.1007/978-3-540-87700-4_78
    
    3 Self-adjusting parameter control for surrogate-assisted constrained 
    optimization under limited budgets
    Samineh Bagheri, Wolfgang Konen, Michael Emmerich, Thomas Baeck
    ELSEVIER Applied Soft Computing 61 (2017) 377-393
        
    4 Wagner, T.; Emmerich, M.; Deutz, A.; Ponweiser, W.: On Expected-
    Improvement Criteria for Model-Based Multi-Objective Optimization.
    In: Proc. 11th Int'l. Conf. Parallel Problem Solving From Nature
    (PPSN XI) - Part I, 11..-15. September, Krakau, Polen, Schaefer, R.;
    Cotta, C.; Kolodziej, J.; Rudolph, G. (Eds.). No. 6238 in Lecture Notes
    in Computer Science, Springer, Berlin, 2010, pp. 718-727.
    ISBN 978-3-642-15843-8. doi: 10.1007/978-3-642-15844-5_72
        
    5 Forrester, A.I.J.; Keane, A.J.; Bressloff, N.W.: Design and analysis of
    'noisy' computer experiments. In: AIAA Journal, 44 (2006) 10,
    pp. 2331-2339. doi: 10.2514/1.20068
    
    call: CONSTRAINED_SMSEGO(problemCall, rngMin, rngMax, ref, nconstraints)
    
    Input arguments
    problemCall: function handle to the objective function (required)
    rngMin: lower bound of the design space (dim)-np array (required)
    rngMax: upper bound of the design space (dim)-np array (required)
    ref: the maximum objective values interested in (required)
    nconstraints: the number of constraints returned by the problemCall (requried)
    
    Optional input arguments:
    initEval: number of initial evaluations, default=11*number of variables-1, 
    maxEval: maximum number of evaluations, default=40*number of variables, 
    smooth: smoothning function, 1=smoothing with exponential kernel, 2=gaussican kernel, 
    runNo: run number controlls the seed, 
    epsilonInit: the "allowed" constrained violation since we are not 100% 
                    confident about the constrained model, default=0.01, 
    epsilonMax= the maximum "allowed" constrained violation, default=0.02
    """
    if problemCall is None or rngMin is None or rngMax is None or ref is None or nconstraints is None:
        raise ValueError('SMSEGO requires at least five arguments (problemCall, rngMin, rngMax, ref, nconstraints)')
    if smooth is None:
        smooth = 2
    nVar = len(rngMin)
    if maxEval is None:
        maxEval = 40*nVar
    if initEval is None:
        initEval = 11*nVar-1 #recommended, but has to be at least larger then n+1
        
    EPS = np.array([epsilonInit]*nconstraints)
    Cfeas = 0
    Cinfeas = 0
    
    print('Calculate initial sampling')    
    functionName = str(problemCall).split(' ')[1]
    outdir = 'results/'+str(functionName)+'/'
    
    if os.path.isdir(outdir) and glob.glob(outdir+'*_finalPF.csv'):
        par_old, con_old, obj_old = include_previous_pareto(initEval, outdir, runNo)
        paretoSize = len(par_old)
        initEvalLHS = initEval - paretoSize
    else:
        paretoSize = 0
        initEvalLHS = max(initEval, 2*nVar+1) #11*nvar = recommended, but has to be at least larger then 2*nVar+1
        
    np.random.seed(runNo)
    if initEvalLHS < 5:
        initEvalLHS = max(11*nVar-1 - paretoSize, 4)
    bestLHS, _, _ = JCS_LHSOptimizer(initEvalLHS, nVar, 10000)
    bestLHS = transformLHS(bestLHS, rngMin, rngMax)
    
    print("evaluate initial sampling")
    nObj = len(ref)
    temp = np.zeros((initEvalLHS, nObj))
    temp2 = np.zeros((initEvalLHS, nconstraints))
    for i in range(initEvalLHS):
        temp[i,:], temp2[i,:] = problemCall(bestLHS[i,:])
    
    if paretoSize == 0:
        parameters = np.empty((maxEval,nVar))
        objectives = np.empty((maxEval, nObj))
        constraints = np.empty((maxEval, nconstraints))
    else:
        parameters = np.append(par_old, np.empty((maxEval,nVar)), axis=0)
        objectives = np.append(obj_old, np.empty((maxEval, nObj)), axis=0)
        constraints = np.append(con_old, np.empty((maxEval, nconstraints)), axis=0)
    
    parameters[paretoSize:,:] = np.NAN
    objectives[paretoSize:,:] = np.NaN
    constraints[paretoSize:,:] = np.NaN
    parameters[paretoSize:paretoSize+initEvalLHS,:] = bestLHS
    objectives[paretoSize:paretoSize+initEvalLHS,:] = temp
    constraints[paretoSize:paretoSize+initEvalLHS,:] = temp2

    evall = initEvalLHS + paretoSize
    maxEval = maxEval + paretoSize

    hypervolumeProgress = np.empty((maxEval,2))
    hypervolumeProgress[:] = np.NAN
    
    Z = -1
    paretoOptimal = np.array([False]*(maxEval))
    for i in range(evall):
        paretoOptimal = np.array([False]*(maxEval))
        paretoOptimal[:i] = paretofrontFeasible(objectives[:i,:],constraints[:i,:])
        paretoFront = objectives[paretoOptimal]
        hypervolumeProgress[i] = [hypervolume(paretoFront, ref),Z]
    
    model = [ [] for i in range(nObj)]
    
    if not os.path.isdir(outdir):
        os.makedirs(outdir)
    
    outputFileParameters = str(outdir)+'par_run'+str(runNo)+'.csv'
    outputFileObjectives = str(outdir)+'obj_run'+str(runNo)+'.csv'
    outputFileConstraints = str(outdir)+'con_run'+str(runNo)+'.csv'
    np.savetxt(outputFileParameters, parameters[:evall], delimiter=',')
    np.savetxt(outputFileObjectives, objectives[:evall], delimiter=',')
    np.savetxt(outputFileConstraints, constraints[:evall], delimiter=',')
    
    paretoOptimal[:evall] = paretofrontFeasible(objectives[:evall,:], constraints[:evall,:])
    paretoFront = objectives[paretoOptimal,:]
    paretoSet = parameters[paretoOptimal]
    paretoConstraints = constraints[paretoOptimal,:]
    
    visualiseParetoFront(paretoFront,save=False)
    print(paretoFront)
    print(paretoConstraints)
    
    start = time.time()
    while evall < maxEval:
        iterationTime = time.time()
        
        print('Compute model for each objective')
        s=time.time()
        model = [ [] for i in range(nObj)]
        if smooth == 0:
            raise ValueError("no smoothing, to be implemented")
        elif smooth==1:
            #smoothing usin gpower exponential kernel with nugget
            pool = multiprocessing.Pool(processes=nObj)
            processs = [(copy.deepcopy(parameters), copy.deepcopy(objectives), evall, obji) for obji in range(nObj)]
            model = pool.map(createExpKrigingModel, processs)
        elif smooth==2:
            #smoothing using gaussian kernel with nugget
            pool = multiprocessing.Pool(processes=nObj)
            processs = [(copy.deepcopy(parameters), copy.deepcopy(objectives), evall, obji) for obji in range(nObj)]
            model = pool.map(createKrigingModel, processs)
        print("Time to compute surrogate models  ",time.time()-s)
        
        print('Optimize infill criterion')
        currentHV = hypervolume(paretoFront, ref)
        hypervolumeProgress[evall] = [currentHV,Z]
        nPF = sum(paretoOptimal)
        if nPF < 2:
            eps = np.zeros((1,nObj))
        else:
            maxima = np.array([max(col) for col in paretoFront.T])
            minima = np.array([min(col) for col in paretoFront.T])
            spread = maxima-minima
            c = 1-(1/np.power(2,nObj))
            eps = spread/(nPF+c*(maxEval-evall))
        gain = -ndtri(0.5*(0.5**(1/float(nObj))))
        
        criterion = partial(optimizeSMSEGOcriterion, model=copy.deepcopy(model), 
                            ref=ref, paretoFront=paretoFront, 
                            currentHV=currentHV, epsilon=np.ndarray.flatten(eps), 
                            gain=gain)
        
        constraintSurrogates = trainCubicRBF(parameters[:evall,:], constraints[:evall], rngMin, rngMax, hypervolumeProgress[:evall])

        X,Z = findAllLocalOptimaNew(copy.deepcopy(model), rngMin, rngMax, criterion, constraintSurrogates, EPS)
        
        if len(X)>0:
            notSeenBefore = ~np.array([x in parameters for x in X])
        else:
            notSeenBefore = [0]
            
        if sum(notSeenBefore)>0:
            print('Filter local optimal')
            ind = np.argmax(notSeenBefore)
            X = X[ind]
        else:
            print('NO FEASIBLE LOCAL MINIMA FOUND!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!')
            X = np.random.rand(nVar)*(rngMax-rngMin)+rngMin
        
        print('Evaluate new solutions')
        parameters[evall,:] = X
        objectiveValues, constraintValues = problemCall(X)
        
        print(objectiveValues)
        print(constraintValues)
        
        objectives[evall,:] = objectiveValues
        constraints[evall,:] = constraintValues
        evall += 1     
        
        np.savetxt(outputFileParameters, parameters[:evall], delimiter=',')
        np.savetxt(outputFileObjectives, objectives[:evall], delimiter=',')
        np.savetxt(outputFileConstraints, constraints[:evall], delimiter=',')
        
        paretoOptimal[:evall] = paretofrontFeasible(objectives[:evall,:],constraints[:evall,:])
        
        paretoFront = objectives[paretoOptimal]
        paretoConstraints = constraints[paretoOptimal]
        visualiseParetoFront(paretoFront,save=False)
        print(paretoFront)
#        print(paretoConstraints)

        feasible = np.all(constraints[evall-1] < 0)            
        Cfeas, Cinfeas, EPS = adjustMargins(Cfeas,Cinfeas,EPS,epsilonMax,nVar,feasible)
        
        print('iteration time', (time.time() - iterationTime))
    #end while
    end = time.time()
    print(end-start)
    
    paretoOptimal[:evall] = paretofrontFeasible(objectives[:evall,:],constraints[:evall,:])
    paretoFront = objectives[paretoOptimal]
    paretoSet = parameters[paretoOptimal]
    paretoConstraints = constraints[paretoOptimal]

    outputFileParameters = str(outdir)+'par_run'+str(runNo)+'_final.csv'
    outputFileObjectives = str(outdir)+'obj_run'+str(runNo)+'_final.csv'
    outputFileConstraints = str(outdir)+'con_run'+str(runNo)+'_final.csv'
    
    np.savetxt(outputFileParameters, parameters, delimiter=',')
    np.savetxt(outputFileObjectives, objectives, delimiter=',')
    np.savetxt(outputFileConstraints, constraints, delimiter=',')

    outputFileParameters = str(outdir)+'par_run'+str(runNo)+'_finalPF.csv'
    outputFileObjectives = str(outdir)+'obj_run'+str(runNo)+'_finalPF.csv'
    outputFileConstraints = str(outdir)+'con_run'+str(runNo)+'_finalPF.csv'
    
    np.savetxt(outputFileObjectives, paretoFront, delimiter=',')
    np.savetxt(outputFileParameters, paretoSet, delimiter=',')
    np.savetxt(outputFileConstraints, paretoConstraints, delimiter=',')

    for d in model:
        d['corr'] = 'corr'
        d['regr'] = 'regr'
        for key in d:
            if type(d[key]) is np.ndarray:
                d[key] = d[key].tolist()
                
    for key in constraintSurrogates:
        if type(constraintSurrogates[key]) is np.ndarray:
            constraintSurrogates[key] = constraintSurrogates[key].tolist()
    
    with open(str(outdir)+str(runNo)+'obj_model.json', 'w') as fOut:
        json.dump(model, fOut)
    
    with open(str(outdir)+str(runNo)+'con_model.json', 'w') as fOut:
        json.dump(constraintSurrogates, fOut)
    
    return objectives, constraints, parameters
